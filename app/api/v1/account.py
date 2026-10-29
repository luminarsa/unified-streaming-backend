from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from fastapi import Depends, HTTPException
from fastapi import Depends, APIRouter
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.identity import Account, Profile
from app.models.commercial import Plan, PlanEntitlement, Subscription
from app.models.platform_config import StreamingPlatform
from app.utils.auth import decode_access_token

bearer_scheme = HTTPBearer()

router = APIRouter(
    prefix="/account",
    tags=["Account"],
)


@router.get("/profiles")
def get_account_profiles(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    # 1. Decode and validate the bearer token.
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
        )

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

    # 2. Fetch the account.
    account = db.get(Account, account_id)

    if account is None:
        raise HTTPException(
            status_code=404,
            detail="Account not found.",
        )

    # 3. Fetch all profiles belonging to the account.
    profiles = (
        db.query(Profile)
        .filter(Profile.account_id == account_id)
        .order_by(Profile.created_at.asc())
        .all()
    )

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

    # 4. Find the account's subscriptions, newest first.
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

    subscription_info = None
    profile_limit = 0
    simultaneous_streams_limit = 0
    has_active_access = False

    # 5. Fetch the plan and its included platforms.
    if subscription is not None:
        plan = db.get(Plan, subscription.plan_id)

        if plan is not None:
            has_active_access = has_subscription_access(subscription)

            simultaneous_streams_limit = (
                plan.max_simultaneous_streams
            )

            # For now, profile creation is limited to the stream
            # allowance only when the subscription grants access.
            profile_limit = (
                simultaneous_streams_limit
                if has_active_access
                else 0
            )

            included_platforms = (
                db.query(StreamingPlatform)
                .join(
                    PlanEntitlement,
                    PlanEntitlement.platform_id
                    == StreamingPlatform.id,
                )
                .filter(
                    PlanEntitlement.plan_id == plan.id,
                    StreamingPlatform.is_active.is_(True),
                )
                .order_by(StreamingPlatform.display_order.asc())
                .all()
            )

            subscription_info = {
                "id": str(subscription.id),
                "plan": {
                    "id": str(plan.id),
                    "code": plan.code,
                    "name": plan.name,
                    "price": (
                        f"{plan.currency} "
                        f"{Decimal(str(plan.price_minor)) / Decimal('100'):.2f}"
                    ),
                    "price_minor": int(plan.price_minor),
                    "currency": plan.currency,
                    "billing_interval": plan.billing_interval,
                },
                "billing_period": {
                    "start_date": (
                        subscription.current_period_start.isoformat()
                        if subscription.current_period_start
                        else None
                    ),
                    "end_date": (
                        subscription.current_period_end.isoformat()
                        if subscription.current_period_end
                        else None
                    ),
                },
                "status": subscription.status,
                "has_active_access": has_active_access,
                "cancel_at_period_end": (
                    subscription.cancel_at_period_end
                ),
                "simultaneous_streams_limit": (
                    simultaneous_streams_limit
                ),
                "platforms_included": [
                    {
                        "id": str(platform.id),
                        "name": platform.name,
                        "slug": platform.slug,
                    }
                    for platform in included_platforms
                ],
            }

    # 6. Return the complete account overview.
    return {
        "profiles": {
            "count": len(profile_list),
            "profile_limit": profile_limit,
            "remaining_slots": max(
                0, profile_limit - len(profile_list)
            ),
            "profiles": profile_list,
        },
        "account": {
            "id": str(account.id),
            "email": account.email,
            "status": account.status,
        },
        "subscription": subscription_info,
        "access": {
            "has_active_subscription": has_active_access,
            "simultaneous_streams_limit": (
                simultaneous_streams_limit
                if has_active_access
                else 0
            ),
        },
    }
