
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.utils.auth import decode_access_token
from app.services.subscriptions import (
    get_account_subscription,
    get_available_plan,
    list_available_plans,
    request_subscription,
    schedule_cancellation,
    create_plan,
    admin_assign_plan_to_account
)


router = APIRouter(tags=["Subscriptions"])
bearer_scheme = HTTPBearer(auto_error=False)


def get_authenticated_account_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
    db: Session = Depends(get_db),
) -> UUID:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )

    token_data = decode_access_token(
        db=db,
        raw_token=credentials.credentials,
    )

    try:
        return UUID(str(token_data["account_id"]))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid account identity in access token.",
        )


# ---------------------------------------------------------
# PUBLIC PLAN CATALOG
# ---------------------------------------------------------
@router.post("/plans", status_code=status.HTTP_201_CREATED)
def create_new_plan(
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    plan = create_plan(db=db, payload=payload)

    return {
        "success": True,
        "message": "Plan created successfully.",
        "data": plan,
    }

@router.post(
    "/admin/accounts/{account_id}/subscriptions",
    status_code=status.HTTP_201_CREATED,
)
def admin_create_account_subscription(
    account_id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    # Add your project's admin authorization dependency here.
) -> dict:
    raw_plan_id = payload.get("plan_id")

    try:
        plan_id = UUID(str(raw_plan_id))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid plan_id UUID is required.",
        )

    result = admin_assign_plan_to_account(
        db=db,
        account_id=account_id,
        plan_id=plan_id,
    )

    return {
        "success": True,
        "message": "Subscription assigned to the account and awaiting payment.",
        "data": result,
    }

@router.get("/plans")
def list_plans(
    db: Session = Depends(get_db),
) -> dict:
    plans = list_available_plans(db)

    return {
        "success": True,
        "count": len(plans),
        "data": plans,
    }


@router.get("/plans/{plan_id}")
def get_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    plan = get_available_plan(db, plan_id)

    return {
        "success": True,
        "data": plan,
    }


# ---------------------------------------------------------
# ACCOUNT SUBSCRIPTIONS
# ---------------------------------------------------------

@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
def create_subscription_request(
    payload: dict,
    account_id: UUID = Depends(get_authenticated_account_id),
    db: Session = Depends(get_db),
) -> dict:
    raw_plan_id = payload.get("plan_id")

    try:
        plan_id = UUID(str(raw_plan_id))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid plan_id UUID is required.",
        )

    subscription = request_subscription(
        db=db,
        account_id=account_id,
        plan_id=plan_id,
    )

    return {
        "success": True,
        "message": "Subscription request created. Payment is still pending.",
        "data": {
            "id": str(subscription.id),
            "account_id": str(subscription.account_id),
            "plan_id": str(subscription.plan_id),
            "status": subscription.status,
            "provider": subscription.provider,
            "current_period_start": subscription.current_period_start,
            "current_period_end": subscription.current_period_end,
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "created_at": subscription.created_at,
            "updated_at": subscription.updated_at,
        },
    }


@router.get("/subscriptions/me")
def get_my_subscription(
    account_id: UUID = Depends(get_authenticated_account_id),
    db: Session = Depends(get_db),
) -> dict:
    result = get_account_subscription(
        db=db,
        account_id=account_id,
    )

    return {
        "success": True,
        "data": result,
    }


@router.post("/subscriptions/me/cancel")
def cancel_my_subscription(
    account_id: UUID = Depends(get_authenticated_account_id),
    db: Session = Depends(get_db),
) -> dict:
    subscription = schedule_cancellation(
        db=db,
        account_id=account_id,
    )

    return {
        "success": True,
        "message": "Subscription cancellation scheduled.",
        "data": {
            "id": str(subscription.id),
            "status": subscription.status,
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "current_period_end": subscription.current_period_end,
            "cancelled_at": subscription.cancelled_at,
        },
    }
