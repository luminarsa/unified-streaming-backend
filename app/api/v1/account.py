from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import Depends, HTTPException, APIRouter, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.schemas.auth import (
    ProfileCreateRequest,
    ProfileCreateResponse,
)
from fastapi import HTTPException, status
from app.db.session import get_db
from app.models.identity import Account, Profile, RegisteredDevice
from app.models.commercial import Plan, PlanEntitlement, Subscription
from app.models.platform_config import StreamingPlatform
from app.utils.auth import decode_access_token
from app.services.auth import create_profile
from app.services.profile_lock_pin_crypto import decrypt_profile_lock_pin
bearer_scheme = HTTPBearer()

router = APIRouter(
    prefix="/account",
    tags=["Account"],
)



@router.get("/profiles")
def get_account_profiles(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    device_installation_id: UUID = Header(
        ...,
        alias="X-Device-Installation-ID",
    ),
    db: Session = Depends(get_db),
):
    # ---------------------------------------------
    # 1. Decode and validate bearer token
    # ---------------------------------------------

    token_data = decode_access_token(
        db=db,
        raw_token=credentials.credentials,
    )

    try:
        account_id = UUID(str(token_data["account_id"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=401,
            detail="Invalid account identity in access token.",
        )

    # ---------------------------------------------
    # 2. Fetch account
    # ---------------------------------------------

    account = db.get(Account, account_id)

    if account is None:
        raise HTTPException(
            status_code=404,
            detail="Account not found.",
        )

    # ---------------------------------------------
    # 3. Identify registered device
    # ---------------------------------------------

    device = db.scalar(
        select(RegisteredDevice).where(
            RegisteredDevice.account_id == account_id,
            RegisteredDevice.device_installation_id == device_installation_id,
        )
    )

    if not device.is_name_confirmed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "DEVICE_NAME_REQUIRED",
                "message": "Please provide a name for this device before loading profiles.",
                "device_id": str(device.id),
            },
        )

    # Update device last-seen timestamp.
    device.last_seen_at = datetime.now(timezone.utc)
    db.commit()

    # ---------------------------------------------
    # 4. Fetch all account profiles
    # ---------------------------------------------

    all_profiles = (
        db.query(Profile)
        .filter(Profile.account_id == account_id)
        .order_by(Profile.created_at.asc())
        .all()
    )

    total_profile_count = len(all_profiles)

    # ---------------------------------------------
    # 5. Apply device profile lock
    # ---------------------------------------------

    if device.locked_profile_id is not None:

        profiles = [
            profile
            for profile in all_profiles
            if profile.id == device.locked_profile_id
        ]

        if not profiles:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "LOCKED_PROFILE_UNAVAILABLE",
                    "message": (
                        "The profile assigned to this device "
                        "is no longer available. The account "
                        "owner must update the device lock."
                    ),
                },
            )

    else:
        profiles = all_profiles

    # ---------------------------------------------
    # 6. Format profiles
    # ---------------------------------------------

    profile_list = [
        {
            "id": str(profile.id),
            "avatar": profile.avatar_key,
            "name": profile.name,
            "account_type": (
                "Kids" if profile.is_kids_profile else "Adult"
            ),
        }
        for profile in profiles
    ]

    # ---------------------------------------------
    # 7. Find account subscription
    # ---------------------------------------------

    subscriptions = (
        db.query(Subscription)
        .filter(Subscription.account_id == account_id)
        .order_by(Subscription.created_at.desc())
        .all()
    )

    now = datetime.now(timezone.utc)

    def has_subscription_access(subscription):
        if subscription.status != "active":
            return False

        if (
            subscription.current_period_start is not None
            and subscription.current_period_start > now
        ):
            return False

        if (
            subscription.current_period_end is not None
            and subscription.current_period_end <= now
        ):
            return False

        if (
            subscription.cancel_at_period_end
            and subscription.current_period_end is None
        ):
            return False

        return True

    # Prefer a subscription that currently grants access.
    subscription = next(
        (
            item for item in subscriptions
            if has_subscription_access(item)
        ),
        subscriptions[0] if subscriptions else None,
    )

    # ---------------------------------------------
    # 8. Calculate account limits from its plan
    # ---------------------------------------------

    profile_limit = 0
    simultaneous_streams_limit = 0
    has_active_access = False

    if subscription is not None:

        plan = db.get(Plan, subscription.plan_id)

        if plan is not None:

            has_active_access = has_subscription_access(
                subscription
            )

            if has_active_access:

                simultaneous_streams_limit = (
                    plan.max_simultaneous_streams
                )

                # Profile limit cannot exceed five or the
                # plan's simultaneous stream allowance.
                profile_limit = min(
                    5,
                    simultaneous_streams_limit,
                )

    # ---------------------------------------------
    # 9. Return account, device and profile details
    # ---------------------------------------------

    return {
        "device": {
            "id": str(device.id),
            "device_installation_id": str(
                device.device_installation_id
            ),
            "device_name": device.device_name,
            "device_type": device.device_type,
            "is_profile_locked": (
                device.locked_profile_id is not None
            ),
            "locked_profile_id": (
                str(device.locked_profile_id)
                if device.locked_profile_id
                else None
            ),
        },
        "profiles": {
            "count": len(profile_list),
            "profile_limit": profile_limit,
            "remaining_slots": max(
                0,
                profile_limit - total_profile_count,
            ),
            "profiles": profile_list,
        },
        "account": {
            "id": str(account.id),
            "email": account.email,
            "status": account.status,
        },
        "access": {
            "has_active_subscription": has_active_access,
            "simultaneous_streams_limit": (
                simultaneous_streams_limit
            ),
        },
    }



# =================================================
# CREATE ADDITIONAL PROFILE
# =================================================

@router.post(
    "/account/profiles",
    status_code=status.HTTP_201_CREATED,
    response_model=ProfileCreateResponse,
)
def create_profile_endpoint(
    request: ProfileCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):

    return create_profile(
        db=db,
        raw_token=credentials.credentials,
        name=request.name,
        avatar_url=request.avatar_url,
        is_kids_profile=request.is_kids_profile,
    )



@router.get("/web-profiles")
def get_web_account_profiles(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    # ---------------------------------------------
    # 1. Decode and validate bearer token
    # ---------------------------------------------

    token_data = decode_access_token(
        db=db,
        raw_token=credentials.credentials,
    )

    try:
        account_id = UUID(str(token_data["account_id"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=401,
            detail="Invalid account identity in access token.",
        )

    # ---------------------------------------------
    # 2. Fetch account
    # ---------------------------------------------

    account = db.get(Account, account_id)

    if account is None:
        raise HTTPException(
            status_code=404,
            detail="Account not found.",
        )

    # ---------------------------------------------
    # 3. Fetch all account profiles
    # ---------------------------------------------

    all_profiles = (
        db.query(Profile)
        .filter(Profile.account_id == account_id)
        .order_by(Profile.created_at.asc())
        .all()
    )

    # ---------------------------------------------
    # 4. Format profiles
    # ---------------------------------------------

    profile_list = [
        {
            "id": str(profile.id),
            "avatar": profile.avatar_key,
            "name": profile.name,
            "account_type": (
                "Kids" if profile.is_kids_profile else "Adult"
            ),
        }
        for profile in all_profiles
    ]

    total_profile_count = len(profile_list)

    # ---------------------------------------------
    # 5. Find account subscription
    # ---------------------------------------------

    subscriptions = (
        db.query(Subscription)
        .filter(Subscription.account_id == account_id)
        .order_by(Subscription.created_at.desc())
        .all()
    )

    now = datetime.now(timezone.utc)

    def has_subscription_access(subscription):
        if subscription.status != "active":
            return False

        if (
            subscription.current_period_start is not None
            and subscription.current_period_start > now
        ):
            return False

        if (
            subscription.current_period_end is not None
            and subscription.current_period_end <= now
        ):
            return False

        if (
            subscription.cancel_at_period_end
            and subscription.current_period_end is None
        ):
            return False

        return True

    # Prefer a subscription that currently grants access.
    subscription = next(
        (
            item for item in subscriptions
            if has_subscription_access(item)
        ),
        subscriptions[0] if subscriptions else None,
    )

    # ---------------------------------------------
    # 6. Calculate account limits from its plan
    # ---------------------------------------------

    profile_limit = 0
    simultaneous_streams_limit = 0
    has_active_access = False

    if subscription is not None:

        plan = db.get(Plan, subscription.plan_id)

        if plan is not None:

            has_active_access = has_subscription_access(
                subscription
            )

            if has_active_access:

                simultaneous_streams_limit = (
                    plan.max_simultaneous_streams
                )

                # Profile limit cannot exceed five or the
                # plan's simultaneous stream allowance.
                profile_limit = min(
                    5,
                    simultaneous_streams_limit,
                )

    # ---------------------------------------------
    # 7. Return account and profile details
    # ---------------------------------------------

    return {
        "profiles": {
            "count": total_profile_count,
            "profile_limit": profile_limit,
            "remaining_slots": max(
                0,
                profile_limit - total_profile_count,
            ),
            "can_create_profile": (
                has_active_access
                and total_profile_count < profile_limit
            ),
            "profiles": profile_list,
        },
        "account": {
            "id": str(account.id),
            "email": account.email,
            "status": account.status,
        },
        "access": {
            "has_active_subscription": has_active_access,
            "simultaneous_streams_limit": (
                simultaneous_streams_limit
            ),
        },
    }


@router.get("/management")
def get_account_management(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    # ---------------------------------------------
    # 1. Decode and validate bearer token
    # ---------------------------------------------

    token_data = decode_access_token(
        db=db,
        raw_token=credentials.credentials,
    )

    try:
        account_id = UUID(str(token_data["account_id"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=401,
            detail="Invalid account identity in access token.",
        )

    # ---------------------------------------------
    # 2. Fetch account
    # ---------------------------------------------

    account = db.get(Account, account_id)

    if account is None:
        raise HTTPException(
            status_code=404,
            detail="Account not found.",
        )

    # ---------------------------------------------
    # 3. Fetch account profiles
    # ---------------------------------------------

    profiles = (
        db.query(Profile)
        .filter(Profile.account_id == account_id)
        .order_by(Profile.created_at.asc())
        .all()
    )

    profile_list = [
        {
            "id": str(profile.id),
            "name": profile.name,
            "avatar": profile.avatar_key,
            "account_type": (
                "Kids" if profile.is_kids_profile else "Adult"
            ),
            "created_at": (
                profile.created_at.isoformat()
                if profile.created_at else None
            ),
        }
        for profile in profiles
    ]

    # ---------------------------------------------
    # 4. Fetch registered devices
    # ---------------------------------------------

    devices = (
        db.query(RegisteredDevice)
        .filter(RegisteredDevice.account_id == account_id)
        .order_by(RegisteredDevice.created_at.desc())
        .all()
    )

    device_list = []

    for device in devices:

        locked_profile = device.locked_profile

        device_list.append({
            "id": str(device.id),
            "device_installation_id": str(
                device.device_installation_id
            ),
            "device_name": device.device_name,
            "device_type": device.device_type,
            "is_name_confirmed": device.is_name_confirmed,
            "is_profile_locked": (
                device.locked_profile_id is not None
            ),
            "locked_profile": (
                {
                    "id": str(locked_profile.id),
                    "name": locked_profile.name,
                    "account_type": (
                        "Kids"
                        if locked_profile.is_kids_profile
                        else "Adult"
                    ),
                }
                if locked_profile is not None
                and locked_profile.account_id == account_id
                else None
            ),
            "last_seen_at": (
                device.last_seen_at.isoformat()
                if device.last_seen_at else None
            ),
            "created_at": (
                device.created_at.isoformat()
                if device.created_at else None
            ),
        })

    # ---------------------------------------------
    # 5. Return account management information
    # ---------------------------------------------

    return {
        "account": {
            "id": str(account.id),
            "email": account.email,
            "phone_number": account.phone_number,
            "status": account.status,
            "email_verified": account.email_verified,
            "email_verified_at": (
                account.email_verified_at.isoformat()
                if account.email_verified_at else None
            ),
            "referral_code_used": account.referral_code_used,
            "has_profile_lock_pin": (
                account.profile_lock_pin_hash is not None
            ),
            "profile_lock_pin": (
                decrypt_profile_lock_pin(account.profile_lock_pin_encrypted)
                if account.profile_lock_pin_encrypted
                else None
            ),
            "created_at": (
                account.created_at.isoformat()
                if account.created_at else None
            ),
            "updated_at": (
                account.updated_at.isoformat()
                if account.updated_at else None
            ),
        },
        "profiles": {
            "count": len(profile_list),
            "profiles": profile_list,
        },
        "devices": {
            "count": len(device_list),
            "devices": device_list,
        },
    }



@router.get("/subscription-management")
def get_account_subscription_management(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    # ---------------------------------------------
    # 1. Decode and validate bearer token
    # ---------------------------------------------

    token_data = decode_access_token(
        db=db,
        raw_token=credentials.credentials,
    )

    try:
        account_id = UUID(str(token_data["account_id"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=401,
            detail="Invalid account identity in access token.",
        )

    # ---------------------------------------------
    # 2. Fetch account
    # ---------------------------------------------

    account = db.get(Account, account_id)

    if account is None:
        raise HTTPException(
            status_code=404,
            detail="Account not found.",
        )

    # ---------------------------------------------
    # 3. Fetch account subscriptions
    # ---------------------------------------------

    subscriptions = (
        db.query(Subscription)
        .filter(Subscription.account_id == account_id)
        .order_by(Subscription.created_at.desc())
        .all()
    )

    now = datetime.now(timezone.utc)

    def has_subscription_access(subscription):
        if subscription.status != "active":
            return False

        if (
            subscription.current_period_start is not None
            and subscription.current_period_start > now
        ):
            return False

        if (
            subscription.current_period_end is not None
            and subscription.current_period_end <= now
        ):
            return False

        if (
            subscription.cancel_at_period_end
            and subscription.current_period_end is None
        ):
            return False

        return True

    # Prefer a subscription that currently grants access.
    subscription = next(
        (
            item for item in subscriptions
            if has_subscription_access(item)
        ),
        subscriptions[0] if subscriptions else None,
    )

    has_active_access = (
        has_subscription_access(subscription)
        if subscription is not None
        else False
    )

    # ---------------------------------------------
    # 4. Fetch all active plans
    # ---------------------------------------------

    available_plans = (
        db.query(Plan)
        .filter(Plan.is_active.is_(True))
        .order_by(
            Plan.price_minor.asc(),
            Plan.name.asc(),
        )
        .all()
    )

    # Include the subscribed plan in the platform lookup
    # even if that plan is no longer offered for new purchases.
    plan_ids = [plan.id for plan in available_plans]

    current_plan = None

    if subscription is not None:
        current_plan = db.get(Plan, subscription.plan_id)

        if (
            current_plan is not None
            and current_plan.id not in plan_ids
        ):
            plan_ids.append(current_plan.id)

    # ---------------------------------------------
    # 5. Fetch platforms included in these plans
    # ---------------------------------------------

    entitlements = []

    if plan_ids:
        entitlements = (
            db.query(
                PlanEntitlement.plan_id,
                StreamingPlatform,
            )
            .join(
                StreamingPlatform,
                StreamingPlatform.id
                == PlanEntitlement.platform_id,
            )
            .filter(
                PlanEntitlement.plan_id.in_(plan_ids),
                StreamingPlatform.is_active.is_(True),
            )
            .order_by(
                StreamingPlatform.display_order.asc(),
                StreamingPlatform.name.asc(),
            )
            .all()
        )

    # Group platform information by plan ID.
    platforms_by_plan = {}

    for plan_id, platform in entitlements:

        platforms_by_plan.setdefault(
            plan_id,
            [],
        ).append({
            "id": str(platform.id),
            "name": platform.name,
            "slug": platform.slug,
            "description": platform.description,
            "logo_url": platform.logo_url,
            "icon": platform.icon,
            "supports_movies": platform.supports_movies,
            "supports_tv_shows": platform.supports_tv_shows,
            "supports_live_tv": platform.supports_live_tv,
        })

    # ---------------------------------------------
    # 6. Format plan information
    # ---------------------------------------------

    def format_plan(plan, is_current_plan=False):

        return {
            "id": str(plan.id),
            "category": plan.category,
            "code": plan.code,
            "name": plan.name,
            "price_minor": int(plan.price_minor),
            "currency": plan.currency,
            "paypal_price": (
                float(plan.paypal_price)
                if plan.paypal_price is not None
                else None
            ),
            "paypal_currency": plan.paypal_currency,
            "billing_interval": plan.billing_interval,
            "max_simultaneous_streams": (
                plan.max_simultaneous_streams
            ),
            "is_active": plan.is_active,
            "is_current_plan": is_current_plan,
            "platforms": platforms_by_plan.get(
                plan.id,
                [],
            ),
        }

    # ---------------------------------------------
    # 7. Format available plans
    # ---------------------------------------------

    plan_list = [
        format_plan(
            plan,
            is_current_plan=(
                has_active_access
                and subscription.plan_id == plan.id
            ),
        )
        for plan in available_plans
    ]

    # ---------------------------------------------
    # 8. Format current subscription
    # ---------------------------------------------

    subscription_data = None
    current_plan_data = None

    if subscription is not None:

        subscription_data = {
            "id": str(subscription.id),
            "status": subscription.status,
            "provider": subscription.provider,
            "provider_subscription_id": (
                subscription.provider_subscription_id
            ),
            "current_period_start": (
                subscription.current_period_start.isoformat()
                if subscription.current_period_start else None
            ),
            "current_period_end": (
                subscription.current_period_end.isoformat()
                if subscription.current_period_end else None
            ),
            "next_billing_at": (
                subscription.next_billing_at.isoformat()
                if subscription.next_billing_at else None
            ),
            "grace_period_ends_at": (
                subscription.grace_period_ends_at.isoformat()
                if subscription.grace_period_ends_at else None
            ),
            "cancel_at_period_end": (
                subscription.cancel_at_period_end
            ),
            "cancelled_at": (
                subscription.cancelled_at.isoformat()
                if subscription.cancelled_at else None
            ),
            "created_at": (
                subscription.created_at.isoformat()
                if subscription.created_at else None
            ),
        }

        if current_plan is not None:
            current_plan_data = format_plan(
                current_plan,
                is_current_plan=has_active_access,
            )

    # ---------------------------------------------
    # 9. Return subscription management information
    # ---------------------------------------------

    return {
        "account": {
            "id": str(account.id),
            "email": account.email,
            "status": account.status,
        },
        "subscription": {
            "has_subscription": subscription is not None,
            "has_active_access": has_active_access,
            "details": subscription_data,
            "current_plan": current_plan_data,
        },
        "available_plans": {
            "count": len(plan_list),
            "plans": plan_list,
        },
    }
