
from decimal import Decimal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.models.platform_config import StreamingPlatform
from app.models.identity import Account, Profile
from app.models.commercial import Plan, Subscription
from app.models.payment_transaction import PaymentTransaction
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
from app.schemas.payment import SubscriptionCheckoutRequest
from app.services.paypal import create_paypal_checkout
from app.services.payment_creation import (
    create_subscription_payment,
    PaymentCreationError,
)
from app.api.v1.dependencies import get_current_account_id


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

@router.get("/paypal/inspect-identity")
async def inspect_paypal_account(
    account_id: str = Depends(get_current_account_id),
):
    try:
        return await inspect_paypal_identity()

    except PayPalError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return {
        "identity": await inspect_paypal_identity(),
        "configuration": get_paypal_diagnostics(),
    }

# ---------------------------------------------------------
# PAYPAL SUBSCRIPTION CHECKOUT
# ---------------------------------------------------------


@router.post(
    "/subscriptions/checkout",
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription_checkout(
    payload: SubscriptionCheckoutRequest,
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> dict:

    try:
        authenticated_account_id = UUID(str(account_id))
        plan_id = UUID(str(payload.plan_id))

        # -----------------------------------------
        # 1. GET AUTHENTICATED ACCOUNT
        # -----------------------------------------

        account = db.query(Account).filter(
            Account.id == authenticated_account_id
        ).first()

        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found.",
            )

        # -----------------------------------------
        # 2. GET PRIMARY PROFILE
        # Oldest profile = primary profile
        # -----------------------------------------

        primary_profile = (
            db.query(Profile)
            .filter(Profile.account_id == account.id)
            .order_by(
                Profile.created_at.asc(),
                Profile.id.asc(),
            )
            .first()
        )

        if not primary_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No customer profile was found for this account.",
            )

        # -----------------------------------------
        # 3. GET SELECTED PLAN
        # -----------------------------------------

        plan = db.query(Plan).filter(
            Plan.id == plan_id
        ).first()

        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscription plan not found.",
            )

        # -----------------------------------------
        # 4. CREATE PENDING SUBSCRIPTION
        # -----------------------------------------

        subscription = Subscription(
            account_id=account.id,
            plan_id=plan.id,
            status="pending",
        )

        db.add(subscription)
        db.flush()

        # -----------------------------------------
        # 5. CREATE PENDING PAYMENT TRANSACTION
        # -----------------------------------------

        transaction = PaymentTransaction(
            subscription_id=subscription.id,
            account_id=account.id,
            transaction_type="initial",
            amount=plan.paypal_price,
            currency="USD",
            status="pending",
            provider="paypal",
        )

        db.add(transaction)
        db.flush()

        # -----------------------------------------
        # 6. CREATE AND SEND PAYPAL INVOICE
        # -----------------------------------------

        paypal_result = await create_paypal_checkout(
            customer_name=primary_profile.name,
            customer_email=account.email,
            plan_name=plan.name,
            subscription_id=str(subscription.id),
            subscription_period="Monthly subscription",
            amount=str(transaction.amount),
            currency=transaction.currency,
        )

        # -----------------------------------------
        # 7. SAVE PAYPAL INVOICE INFORMATION
        # -----------------------------------------

        transaction.provider_invoice_id = paypal_result["invoice_id"]
        transaction.provider_invoice_status = paypal_result["invoice_status"]
        transaction.provider_invoice_url = paypal_result["invoice_url"]

        db.commit()

        db.refresh(subscription)
        db.refresh(transaction)

        # -----------------------------------------
        # 8. RETURN CHECKOUT RESPONSE
        # -----------------------------------------

        return {
            "success": True,
            "message": "PayPal invoice created and sent successfully.",
            "subscription_id": str(subscription.id),
            "transaction_id": str(transaction.id),
            "invoice_id": paypal_result["invoice_id"],
            "invoice_url": paypal_result["invoice_url"],
            "amount": paypal_result["amount"],
            "currency": paypal_result["currency"],
            "payment_status": "pending",
            "invoice_status": paypal_result["invoice_status"],
        }

    except ValueError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid account ID or plan ID is required.",
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()

        # Do not expose internal exception details to the client.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create the PayPal checkout invoice.",
        )
    
@router.get("/platforms", status_code=status.HTTP_200_OK)
def get_lumina_platforms(
    db: Session = Depends(get_db),
):
    platforms = (
        db.query(StreamingPlatform)
        .filter(StreamingPlatform.is_active == True)
        .order_by(StreamingPlatform.created_at.asc())
        .all()
    )

    return [
        {
            "id": p.id,
            "name": p.name,
            "logo": p.logo_url
        }
        for p in platforms
    ]

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
