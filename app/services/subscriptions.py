
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
        "code": plan.code,
        "name": plan.name,
        "price_minor": plan.price_minor,
        "currency": plan.currency,
        "billing_interval": plan.billing_interval,
        "is_active": plan.is_active,
        "max_simultaneous_streams": plan.max_simultaneous_streams,
        "created_at": plan.created_at,
        "platforms": [
            {
                "id": platform.id,
                "name": platform.name,
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


def create_plan(db: Session, payload: dict) -> dict:
    """
    Create a plan, its platform entitlements, and its features
    in one database transaction.
    """

    # 1. Validate required fields
    code = str(payload.get("code", "")).strip().upper()
    name = str(payload.get("name", "")).strip()

    if not code or not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Both code and name are required.",
        )

    # 2. Validate price
    try:
        price_minor = int(payload["price_minor"])
        if price_minor < 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="price_minor must be a non-negative integer in cents.",
        )

    # Prevent decimal values such as 9900.50 being silently accepted.
    if isinstance(payload["price_minor"], bool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="price_minor must be an integer.",
        )

    if isinstance(payload["price_minor"], float) and not payload["price_minor"].is_integer():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="price_minor must be an integer.",
        )

    # 3. Validate simultaneous streams
    try:
        max_streams = int(payload.get("max_simultaneous_streams", 1))
        if max_streams < 1:
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="max_simultaneous_streams must be at least 1.",
        )

    # 4. Validate included platforms and features
    platform_slugs = payload.get("platforms", [])
    features = payload.get("features", {})

    if not isinstance(platform_slugs, list):
        raise HTTPException(
            status_code=422,
            detail="platforms must be a list of platform slugs.",
        )

    if len(platform_slugs) != len(set(platform_slugs)):
        raise HTTPException(
            status_code=422,
            detail="Duplicate platform slugs are not allowed.",
        )

    if not isinstance(features, dict):
        raise HTTPException(
            status_code=422,
            detail="features must be an object of feature codes and boolean values.",
        )

    if any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(value, bool)
        for key, value in features.items()
    ):
        raise HTTPException(
            status_code=422,
            detail="Each feature must have a non-empty code and a boolean value.",
        )

    # 5. Check whether the plan code already exists
    existing_plan = db.scalar(
        select(Plan).where(Plan.code == code)
    )

    if existing_plan:
        raise HTTPException(
            status_code=409,
            detail=f"A plan with code '{code}' already exists.",
        )

    # 6. Resolve platform slugs to actual platform records
    platforms = []

    if platform_slugs:
        platforms = list(
            db.scalars(
                select(StreamingPlatform).where(
                    StreamingPlatform.slug.in_(platform_slugs),
                    StreamingPlatform.is_active.is_(True),
                )
            ).all()
        )

    found_slugs = {platform.slug for platform in platforms}
    missing_slugs = set(platform_slugs) - found_slugs

    if missing_slugs:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Some platforms do not exist or are inactive.",
                "platforms": sorted(missing_slugs),
            },
        )

    # 7. Create the plan and all related records atomically
    try:
        plan = Plan(
            code=code,
            name=name,
            price_minor=price_minor,
            currency="ZAR",
            billing_interval=payload.get("billing_interval", "Monthly"),
            max_simultaneous_streams=max_streams,
            is_active=payload.get("is_active", True),
        )

        db.add(plan)
        db.flush()  # Generates the plan UUID before adding related rows.

        for platform in platforms:
            db.add(
                PlanEntitlement(
                    plan_id=plan.id,
                    platform_id=platform.id,
                )
            )

        for feature_code, is_enabled in features.items():
            db.add(
                PlanFeature(
                    plan_id=plan.id,
                    feature_code=feature_code.strip().lower(),
                    is_enabled=is_enabled,
                )
            )

        db.commit()
        db.refresh(plan)

        return {
            "id": str(plan.id),
            "code": plan.code,
            "name": plan.name,
            "price_minor": int(plan.price_minor),
            "price_zar": f"R{Decimal(str(plan.price_minor)) / Decimal('100'):.2f}",
            "currency": plan.currency,
            "billing_interval": plan.billing_interval,
            "max_simultaneous_streams": plan.max_simultaneous_streams,
            "is_active": plan.is_active,
            "platforms": [
                {
                    "id": str(platform.id),
                    "name": platform.name,
                    "slug": platform.slug,
                }
                for platform in platforms
            ],
            "features": features,
            "created_at": plan.created_at.isoformat()
            if plan.created_at
            else None,
        }

    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
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