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
