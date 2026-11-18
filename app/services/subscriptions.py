
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.commercial import Plan, PlanEntitlement
from app.models.platform_config import StreamingPlatform
from app.schemas.plans import PlanCreateRequest


from app.models.commercial import (
    Plan,
    PlanEntitlement,
    PlanFeature,
    Subscription,
)
from app.models.identity import Account
from app.models.platform_config import StreamingPlatform


# ---------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------

def _commit(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=message)


def _get_plan(db: Session, plan_id: UUID) -> Plan:
    plan = db.get(Plan, plan_id)

    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found.")

    return plan


def _plan_data(db: Session, plan: Plan) -> dict:
    platforms = db.scalars(
        select(StreamingPlatform)
        .join(
            PlanEntitlement,
            PlanEntitlement.platform_id == StreamingPlatform.id,
        )
        .where(
            PlanEntitlement.plan_id == plan.id,
            StreamingPlatform.is_active.is_(True),
        )
        .order_by(
            StreamingPlatform.display_order,
            StreamingPlatform.name,
        )
    ).all()

    features = db.scalars(
        select(PlanFeature)
        .where(PlanFeature.plan_id == plan.id)
        .order_by(PlanFeature.feature_code)
    ).all()

    return {
        "id": plan.id,
        "category": plan.category,
        "code": plan.code,
        "name": plan.name,
        "price_minor": (plan.price_minor / 1000),
        "currency": plan.currency,
        "paypal_price": plan.paypal_price,
        "paypal_curreny": plan.paypal_currency,
        "billing_interval": plan.billing_interval,
        "is_active": plan.is_active,
        "max_simultaneous_streams": plan.max_simultaneous_streams,
        "created_at": plan.created_at,
        "platforms": [
            {
                "id": platform.id,
                "name": platform.name,
                "logo": platform.logo_url,
                "slug": platform.slug,
                "supports_movies": platform.supports_movies,
                "supports_tv_shows": platform.supports_tv_shows,
                "supports_live_tv": platform.supports_live_tv,
            }
            for platform in platforms
        ],
        "features": [
            {
                "feature_code": feature.feature_code,
                "is_enabled": feature.is_enabled,
            }
            for feature in features
        ],
    }


# ---------------------------------------------------------
# PLAN CATALOG
# ---------------------------------------------------------

def list_available_plans(db: Session) -> list[dict]:
    plans = db.scalars(
        select(Plan)
        .where(Plan.is_active.is_(True))
        .order_by(Plan.price_minor, Plan.name)
    ).all()

    return [_plan_data(db, plan) for plan in plans]


def get_available_plan(db: Session, plan_id: UUID) -> dict:
    plan = _get_plan(db, plan_id)

    if not plan.is_active:
        raise HTTPException(
            status_code=404,
            detail="This plan is not currently available.",
        )

    return _plan_data(db, plan)


# ---------------------------------------------------------
# SUBSCRIPTION STATUS
# ---------------------------------------------------------

def subscription_has_access(subscription: Subscription) -> bool:
    now = datetime.now(timezone.utc)

    if subscription.status != "active":
        return False

    if (
        subscription.current_period_start is not None
        and subscription.current_period_start > now
    ):
        return False

    if subscription.cancel_at_period_end:
        return (
            subscription.current_period_end is not None
            and subscription.current_period_end > now
        )

    if (
        subscription.current_period_end is not None
        and subscription.current_period_end <= now
    ):
        return False

    return True


def get_account_subscription(
    db: Session,
    account_id: UUID,
) -> dict:
    subscription = db.scalar(
        select(Subscription)
        .where(Subscription.account_id == account_id)
        .order_by(
            Subscription.created_at.desc(),
            Subscription.id.desc(),
        )
        .limit(1)
    )

    if subscription is None:
        return {
            "subscription": None,
            "plan": None,
            "access_active": False,
        }

    plan = db.get(Plan, subscription.plan_id)

    return {
        "subscription": subscription,
        "plan": _plan_data(db, plan) if plan is not None else None,
        "access_active": subscription_has_access(subscription),
    }


# ---------------------------------------------------------
# REQUEST A SUBSCRIPTION
# ---------------------------------------------------------

def request_subscription(
    db: Session,
    account_id: UUID,
    plan_id: UUID,
) -> Subscription:
    plan = _get_plan(db, plan_id)

    if not plan.is_active:
        raise HTTPException(
            status_code=400,
            detail="This plan is not currently available.",
        )

    now = datetime.now(timezone.utc)

    existing_subscriptions = db.scalars(
        select(Subscription)
        .where(
            Subscription.account_id == account_id,
            Subscription.status.in_(["pending", "active"]),
        )
        .order_by(Subscription.created_at.desc())
    ).all()

    for existing in existing_subscriptions:
        if existing.status == "pending":
            raise HTTPException(
                status_code=409,
                detail=(
                    "You already have a pending subscription request. "
                    "Resolve it before requesting another plan."
                ),
            )

        if subscription_has_access(existing):
            raise HTTPException(
                status_code=409,
                detail=(
                    "You already have an active subscription. "
                    "Use the plan-change process to switch plans."
                ),
            )

        # An active subscription with a future cancellation date
        # remains usable until that period ends.
        if (
            existing.status == "active"
            and existing.cancel_at_period_end
            and existing.current_period_end is not None
            and existing.current_period_end > now
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Your current subscription remains active until "
                    "the end of its billing period."
                ),
            )

    subscription = Subscription(
        account_id=account_id,
        plan_id=plan.id,
        status="pending",
        cancel_at_period_end=False,
    )

    db.add(subscription)
    _commit(db, "Unable to create the subscription request.")
    db.refresh(subscription)

    return subscription


# ---------------------------------------------------------
# SCHEDULE CANCELLATION
# ---------------------------------------------------------

def schedule_cancellation(
    db: Session,
    account_id: UUID,
) -> Subscription:
    subscription = db.scalar(
        select(Subscription)
        .where(
            Subscription.account_id == account_id,
            Subscription.status == "active",
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )

    if subscription is None or not subscription_has_access(subscription):
        raise HTTPException(
            status_code=404,
            detail="No active subscription was found.",
        )

    if subscription.current_period_end is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "The subscription has no billing-period end date. "
                "Cancellation scheduling requires a valid billing period."
            ),
        )

    if subscription.cancel_at_period_end:
        return subscription

    subscription.cancel_at_period_end = True

    _commit(db, "Unable to schedule subscription cancellation.")
    db.refresh(subscription)

    return subscription


# ---------------------------------------------------------
# ENTITLEMENTS FOR DOWNSTREAM SERVICES
# ---------------------------------------------------------

def get_account_entitlements(
    db: Session,
    account_id: UUID,
) -> dict:
    """
    Resolve the account's current platform and feature permissions.

    This function can be called by the platform home service and
    the live TV service. It does not trust client-supplied plan IDs.
    """
    subscription = db.scalar(
        select(Subscription)
        .where(
            Subscription.account_id == account_id,
            Subscription.status == "active",
        )
        .order_by(Subscription.created_at.desc())
    )

    if (
        subscription is None
        or not subscription_has_access(subscription)
    ):
        return {
            "has_subscription": False,
            "plan_id": None,
            "platform_ids": set(),
            "features": set(),
            "max_simultaneous_streams": 0,
        }

    plan = db.get(Plan, subscription.plan_id)

    if plan is None or not plan.is_active:
        return {
            "has_subscription": False,
            "plan_id": None,
            "platform_ids": set(),
            "features": set(),
            "max_simultaneous_streams": 0,
        }

    platform_ids = set(
        db.scalars(
            select(PlanEntitlement.platform_id)
            .join(
                StreamingPlatform,
                StreamingPlatform.id == PlanEntitlement.platform_id,
            )
            .where(
                PlanEntitlement.plan_id == plan.id,
                StreamingPlatform.is_active.is_(True),
            )
        ).all()
    )

    enabled_features = set(
        db.scalars(
            select(PlanFeature.feature_code)
            .where(
                PlanFeature.plan_id == plan.id,
                PlanFeature.is_enabled.is_(True),
            )
        ).all()
    )

    return {
        "has_subscription": True,
        "plan_id": plan.id,
        "platform_ids": platform_ids,
        "features": enabled_features,
        "max_simultaneous_streams": plan.max_simultaneous_streams,
    }


def create_plan(db: Session, payload: PlanCreateRequest) -> dict:
    """
    Create a plan and its platform entitlements
    in one database transaction.

    If entitlements is empty, all active platforms
    will automatically be included.
    """

    # -----------------------------------------
    # 1. CHECK IF PLAN CODE ALREADY EXISTS
    # -----------------------------------------

    existing_plan = db.scalar(
        select(Plan).where(
            Plan.code == payload.code
        )
    )

    if existing_plan:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A plan with code '{payload.code}' already exists.",
        )

    # -----------------------------------------
    # 2. RESOLVE PLATFORM ENTITLEMENTS
    # -----------------------------------------

    if payload.entitlements:

        # Only include the platforms specified by the frontend.
        platforms = list(
            db.scalars(
                select(StreamingPlatform).where(
                    StreamingPlatform.id.in_(payload.entitlements),
                    StreamingPlatform.is_active.is_(True),
                )
            ).all()
        )

        found_ids = {
            platform.id for platform in platforms
        }

        missing_ids = set(payload.entitlements) - found_ids

        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Some platform IDs do not exist or are inactive.",
                    "platform_ids": [
                        str(platform_id)
                        for platform_id in missing_ids
                    ],
                },
            )

    else:

        # Empty entitlements means include ALL active platforms.
        platforms = list(
            db.scalars(
                select(StreamingPlatform).where(
                    StreamingPlatform.is_active.is_(True)
                )
            ).all()
        )

    # -----------------------------------------
    # 3. CREATE PLAN AND ENTITLEMENTS
    # -----------------------------------------

    try:

        plan = Plan(
            category=payload.category,
            code=payload.code,
            name=payload.name,

            price_minor=payload.price_minor,
            currency=payload.currency,

            paypal_price=payload.paypal_price,
            paypal_currency=payload.paypal_currency,

            billing_interval=payload.billing_interval,
            max_simultaneous_streams=payload.max_simultaneous_streams,

            is_active=payload.is_active,
        )

        db.add(plan)
        db.flush()

        # Create platform entitlement records.
        for platform in platforms:

            db.add(
                PlanEntitlement(
                    plan_id=plan.id,
                    platform_id=platform.id,
                )
            )

        # Commit everything together.
        db.commit()
        db.refresh(plan)

        # -----------------------------------------
        # 4. RETURN CREATED PLAN
        # -----------------------------------------

        return {
            "id": plan.id,

            "category": plan.category,
            "code": plan.code,
            "name": plan.name,

            "price_minor": int(plan.price_minor),

            "price_zar": (
                f"R{Decimal(str(plan.price_minor)) / Decimal('100'):.2f}"
            ),

            "currency": plan.currency,

            "paypal_price": plan.paypal_price,
            "paypal_currency": plan.paypal_currency,

            "billing_interval": plan.billing_interval,
            "max_simultaneous_streams": plan.max_simultaneous_streams,

            "is_active": plan.is_active,

            "entitlements": [
                {
                    "id": platform.id,
                    "name": platform.name,
                    "slug": platform.slug,
                }
                for platform in platforms
            ],

            "created_at": plan.created_at,
        }

    except IntegrityError as exc:

        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The plan could not be created because of a database constraint.",
        ) from exc

    except Exception:

        db.rollback()
        raise


def admin_assign_plan_to_account(
    db: Session,
    account_id: UUID,
    plan_id: UUID,
) -> dict:
    """
    Create a pending subscription for a customer account.
    Payment confirmation and activation happen separately.
    """

    # 1. Find the customer account
    account = db.scalar(
        select(Account).where(Account.id == account_id)
    )

    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer account was not found.",
        )

    if account.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot assign a subscription to an inactive account.",
        )

    # 2. Find the plan
    plan = db.scalar(
        select(Plan).where(Plan.id == plan_id)
    )

    if plan is None or not plan.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan was not found or is inactive.",
        )

    # 3. Prevent duplicate pending or active subscriptions
    existing_subscription = db.scalar(
        select(Subscription)
        .where(
            Subscription.account_id == account_id,
            Subscription.status.in_(["pending", "active"]),
        )
        .order_by(Subscription.created_at.desc())
    )

    if existing_subscription is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "This account already has a pending or active "
                    "subscription. Resolve it before assigning another plan."
                ),
                "existing_subscription_id": str(
                    existing_subscription.id
                ),
                "existing_status": existing_subscription.status,
            },
        )

    # 4. Create the subscription as pending
    subscription = Subscription(
        account_id=account_id,
        plan_id=plan_id,
        status="pending",
        cancel_at_period_end=False,
    )

    try:
        db.add(subscription)
        db.commit()
        db.refresh(subscription)

    except Exception:
        db.rollback()
        raise

    # 5. Return a dictionary
    return {
        "id": str(subscription.id),
        "account_id": str(subscription.account_id),
        "plan_id": str(subscription.plan_id),
        "plan_code": plan.code,
        "plan_name": plan.name,
        "plan_price_minor": int(plan.price_minor),
        "plan_price_zar": (
            f"R{int(plan.price_minor) / 100:.2f}"
        ),
        "status": subscription.status,
        "provider": subscription.provider,
        "current_period_start": (
            subscription.current_period_start.isoformat()
            if subscription.current_period_start
            else None
        ),
        "current_period_end": (
            subscription.current_period_end.isoformat()
            if subscription.current_period_end
            else None
        ),
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "created_at": (
            subscription.created_at.isoformat()
            if subscription.created_at
            else None
        ),
    }