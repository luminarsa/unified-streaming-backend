
import uuid

from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.commercial import Plan, Subscription
from app.models.identity import Profile
from app.models.payment_transaction import PaymentTransaction
from app.services import paypal


# ---------------------------------------------------------
# 1. GET AND VALIDATE PLAN
# ---------------------------------------------------------

def _get_plan(db: Session, plan_id: str) -> Plan:
    try:
        plan_uuid = uuid.UUID(plan_id)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail="Invalid plan ID.",
        )

    plan = (
        db.query(Plan)
        .filter(
            Plan.id == plan_uuid,
            Plan.is_active == True,
        )
        .first()
    )

    if not plan:
        raise HTTPException(
            status_code=404,
            detail="Plan not found or inactive.",
        )

    return plan


# ---------------------------------------------------------
# 2. FORMAT PAYPAL AMOUNT
# ---------------------------------------------------------

def _get_paypal_amount(plan: Plan) -> Decimal:
    if plan.paypal_price is None:
        raise HTTPException(
            status_code=400,
            detail="This plan does not have a PayPal price configured.",
        )

    if not plan.paypal_currency:
        raise HTTPException(
            status_code=400,
            detail="This plan does not have a PayPal currency configured.",
        )

    try:
        amount = Decimal(str(plan.paypal_price))
    except (InvalidOperation, ValueError):
        raise HTTPException(
            status_code=400,
            detail="The PayPal price configured for this plan is invalid.",
        )

    if not amount.is_finite() or amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="The PayPal price must be greater than zero.",
        )

    return amount.quantize(Decimal("0.01"))


def _format_amount(amount: Decimal) -> str:
    return f"{amount:.2f}"


# ---------------------------------------------------------
# 3. CREATE CHECKOUT
# ---------------------------------------------------------

async def create_checkout(
    db: Session,
    profile: Profile,
    plan_id: str,
    card_single_use_token: str | None = None,
):
    """
    Creates a pending subscription and PayPal order.

    If a PayPal card single-use token is supplied, the card
    checkout/vaulting flow is used.

    Otherwise, a standard PayPal checkout order is created.

    The client must never supply the authoritative amount.
    The amount always comes from the database Plan record.
    """

    plan = _get_plan(db, plan_id)

    amount = _get_paypal_amount(plan)
    formatted_amount = _format_amount(amount)

    currency = plan.paypal_currency.upper()

    if len(currency) != 3:
        raise HTTPException(
            status_code=400,
            detail="The PayPal currency configuration is invalid.",
        )

    # Create a pending subscription.
    subscription = Subscription(
        account_id=profile.account_id,
        plan_id=plan.id,
        status="pending",
        provider="paypal",
    )

    db.add(subscription)
    db.flush()

    # Create a pending transaction.
    transaction = PaymentTransaction(
        account_id=profile.account_id,
        subscription_id=subscription.id,
        provider="paypal",
        transaction_type="initial",
        amount=amount,
        currency=currency,
        status="pending",
    )

    db.add(transaction)
    db.commit()

    db.refresh(subscription)
    db.refresh(transaction)

    # Unique request ID makes checkout retries safer.
    request_id = str(uuid.uuid4())

    try:
        if card_single_use_token:
            order = await paypal.create_card_order(
                amount=formatted_amount,
                currency=currency,
                subscription_id=str(subscription.id),
                plan_name=plan.name,
                card_single_use_token=card_single_use_token,
                request_id=request_id,
            )
        else:
            order = await paypal.create_order(
                amount=formatted_amount,
                currency=currency,
                subscription_id=str(subscription.id),
                plan_name=plan.name,
                request_id=request_id,
            )

        order_id = order.get("id")

        if not order_id:
            raise paypal.PayPalError(
                "PayPal did not return an order ID."
            )

        transaction.provider_order_id = order_id

        db.commit()

        return {
            "order_id": order_id,
            "subscription_id": str(subscription.id),
            "transaction_id": str(transaction.id),
            "status": order.get("status", "CREATED"),
            "currency": currency,
            "amount": formatted_amount,
        }

    except paypal.PayPalError as exc:
        transaction.status = "failed"
        transaction.failure_message = str(exc)[:500]

        subscription.status = "failed"

        db.commit()

        raise HTTPException(
            status_code=502,
            detail="Unable to create PayPal checkout.",
        )


# ---------------------------------------------------------
# 4. CAPTURE AND VERIFY CHECKOUT
# ---------------------------------------------------------

async def capture_checkout(
    db: Session,
    profile: Profile,
    order_id: str,
):
    """
    Captures an approved PayPal order.

    Verifies:
    - The order belongs to this account.
    - The order references the correct subscription.
    - The order amount and currency match the plan.
    - The capture was completed successfully.

    Only then is the subscription activated.
    """

    if not order_id:
        raise HTTPException(
            status_code=400,
            detail="PayPal order ID is required.",
        )

    # Find the transaction belonging to this account.
    transaction = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.provider_order_id == order_id,
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

    # Return the existing result if already processed.
    if transaction.status == "completed":
        subscription = (
            db.query(Subscription)
            .filter(
                Subscription.id == transaction.subscription_id,
                Subscription.account_id == profile.account_id,
            )
            .first()
        )

        return {
            "order_id": order_id,
            "subscription_id": str(subscription.id),
            "payment_status": "COMPLETED",
            "subscription_status": subscription.status,
        }

    # If PayPal capture has already been recorded,
    # wait for the webhook to finalise the payment.
    if transaction.status == "processing" and transaction.provider_capture_id:
        subscription = (
            db.query(Subscription)
            .filter(
                Subscription.id == transaction.subscription_id,
                Subscription.account_id == profile.account_id,
            )
            .first()
        )

        return {
            "order_id": order_id,
            "capture_id": transaction.provider_capture_id,
            "transaction_id": str(transaction.id),
            "subscription_id": str(transaction.subscription_id),
            "payment_status": "PROCESSING",
            "subscription_status": subscription.status if subscription else "pending",
        }

    if transaction.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="This payment transaction cannot be captured.",
        )

    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.id == transaction.subscription_id,
            Subscription.account_id == profile.account_id,
            Subscription.provider == "paypal",
        )
        .first()
    )

    if not subscription:
        raise HTTPException(
            status_code=404,
            detail="Subscription not found.",
        )

    if subscription.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="This subscription is not awaiting payment.",
        )

    plan = (
        db.query(Plan)
        .filter(Plan.id == subscription.plan_id)
        .first()
    )

    if not plan:
        raise HTTPException(
            status_code=404,
            detail="Subscription plan no longer exists.",
        )

    expected_amount = _get_paypal_amount(plan)
    expected_currency = plan.paypal_currency.upper()

    # -----------------------------------------------------
    # Retrieve the order from PayPal
    # -----------------------------------------------------

    try:
        order = await paypal.get_order(order_id)

    except paypal.PayPalError as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to verify the PayPal order.",
        ) from exc

    purchase_units = order.get("purchase_units", [])

    if not purchase_units:
        raise HTTPException(
            status_code=400,
            detail="PayPal order has no purchase unit.",
        )

    purchase_unit = purchase_units[0]

    # Verify that PayPal's order references our subscription.
    paypal_subscription_reference = (
        purchase_unit.get("reference_id")
        or purchase_unit.get("custom_id")
    )

    if paypal_subscription_reference != str(subscription.id):
        raise HTTPException(
            status_code=400,
            detail="PayPal order does not match this subscription.",
        )

    # Check the amount before attempting capture.
    order_amount = purchase_unit.get("amount", {})

    order_amount_value = order_amount.get("value")
    order_currency = order_amount.get("currency_code")

    try:
        actual_order_amount = Decimal(str(order_amount_value))
    except (InvalidOperation, ValueError):
        raise HTTPException(
            status_code=400,
            detail="PayPal order contains an invalid amount.",
        )

    if (
        actual_order_amount != expected_amount
        or order_currency != expected_currency
    ):
        raise HTTPException(
            status_code=400,
            detail="PayPal order amount does not match the subscription plan.",
        )

    # Only capture an order that has been approved.
    if order.get("status") != "APPROVED":
        raise HTTPException(
            status_code=409,
            detail="PayPal order has not been approved for capture.",
        )

    # -----------------------------------------------------
    # Capture payment
    # -----------------------------------------------------

    transaction.status = "processing"
    db.commit()

    # Stable request ID for retries of this capture.
    capture_request_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"unified-streaming-capture:{order_id}",
        )
    )

    try:
        capture_result = await paypal.capture_order(
            order_id,
            request_id=capture_request_id,
        )

    except paypal.PayPalError as exc:
        # Keep processing status because the request may have
        # reached PayPal even if our connection failed.
        # Reconcile the order before attempting another capture.
        transaction.failure_message = str(exc)[:500]
        db.commit()

        raise HTTPException(
            status_code=502,
            detail="Unable to confirm PayPal payment capture. Payment requires reconciliation.",
        ) from exc

    # -----------------------------------------------------
    # Verify capture response
    # -----------------------------------------------------

    if capture_result.get("status") != "COMPLETED":
        transaction.status = "failed"
        transaction.failure_message = (
            "PayPal did not report a completed capture."
        )

        subscription.status = "pending"

        db.commit()

        raise HTTPException(
            status_code=402,
            detail="PayPal payment was not completed.",
        )

    capture_units = capture_result.get("purchase_units", [])

    if not capture_units:
        raise HTTPException(
            status_code=502,
            detail="PayPal capture response is missing purchase units.",
        )

    payments = capture_units[0].get("payments", {})
    captures = payments.get("captures", [])

    if not captures:
        raise HTTPException(
            status_code=502,
            detail="PayPal capture response is missing capture details.",
        )

    capture = captures[0]

    if capture.get("status") != "COMPLETED":
        raise HTTPException(
            status_code=402,
            detail="Payment capture was not completed.",
        )

    capture_amount = capture.get("amount", {})

    try:
        actual_capture_amount = Decimal(
            str(capture_amount.get("value"))
        )
    except (InvalidOperation, ValueError):
        raise HTTPException(
            status_code=502,
            detail="PayPal capture returned an invalid amount.",
        )

    actual_capture_currency = capture_amount.get("currency_code")

    if (
        actual_capture_amount != expected_amount
        or actual_capture_currency != expected_currency
    ):
        # Payment may already have been collected.
        # Do not activate the subscription automatically.
        transaction.status = "processing"
        transaction.failure_message = (
            "Captured amount or currency does not match the plan. "
            "Manual reconciliation is required."
        )

        db.commit()

        raise HTTPException(
            status_code=502,
            detail="Captured payment requires manual reconciliation.",
        )

    capture_id = capture.get("id")

    if not capture_id:
        transaction.status = "processing"
        transaction.failure_message = (
            "PayPal capture response did not contain a capture ID."
        )

        db.commit()

        raise HTTPException(
            status_code=502,
            detail="PayPal capture requires manual reconciliation.",
        )

    # -----------------------------------------------------
    # Record successful PayPal capture
    # -----------------------------------------------------

    # Important:
    # Do not activate the subscription here.
    # The verified PayPal webhook will do that.

    transaction.provider_capture_id = capture_id
    transaction.provider_transaction_id = capture_id
    transaction.status = "processing"
    transaction.failure_message = None

    db.commit()
    db.refresh(transaction)

    return {
        "order_id": order_id,
        "capture_id": capture_id,
        "transaction_id": str(transaction.id),
        "subscription_id": str(subscription.id),
        "payment_status": "PROCESSING",
        "subscription_status": "pending",
        "currency": expected_currency,
        "amount": _format_amount(expected_amount),
        "message": "Payment captured. Awaiting PayPal webhook confirmation.",
    }