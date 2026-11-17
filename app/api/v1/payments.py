
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.v1.dependencies import get_active_profile
from app.models.identity import Profile
from app.models.payment_transaction import PaymentTransaction
from app.models.commercial import Subscription

from app.schemas.payments import (
    CreateCheckoutRequest,
    CreateCheckoutResponse,
    CapturePaymentRequest,
    CapturePaymentResponse,
)

from app.services.payments import (
    create_checkout,
    capture_checkout,
)


router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


@router.post(
    "/checkout",
    response_model=CreateCheckoutResponse,
)
async def checkout(
    request: CreateCheckoutRequest,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    result = await create_checkout(
        db=db,
        profile=profile,
        plan_id=request.plan_id,
    )

    return result


@router.post(
    "/capture",
    response_model=CapturePaymentResponse,
)
async def capture(
    request: CapturePaymentRequest,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    result = await capture_checkout(
        db=db,
        profile=profile,
        order_id=request.order_id,
    )

    return result


@router.get("/status/{transaction_id}")
def get_payment_status(
    transaction_id: str,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    # Find the payment transaction belonging to this account.
    transaction = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.id == transaction_id,
            PaymentTransaction.account_id == profile.account_id,
            PaymentTransaction.provider == "paypal",
        )
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Payment transaction not found.",
        )

    # Find the subscription associated with this transaction.
    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.id == transaction.subscription_id,
            Subscription.account_id == profile.account_id,
        )
        .first()
    )

    if not subscription:
        raise HTTPException(
            status_code=404,
            detail="Subscription associated with this payment was not found.",
        )

    return {
        "transaction_id": str(transaction.id),
        "order_id": transaction.provider_order_id,
        "capture_id": transaction.provider_capture_id,
        "payment_status": transaction.status,
        "subscription_id": str(subscription.id),
        "subscription_status": subscription.status,
        "amount": str(transaction.amount),
        "currency": transaction.currency,
        "created_at": transaction.created_at,
        "updated_at": transaction.updated_at,
    }