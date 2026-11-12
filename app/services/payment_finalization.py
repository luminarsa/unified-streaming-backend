import calendar
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.commercial import Subscription
from app.models.payment_transaction import PaymentTransaction


# ---------------------------------------------------------
# 1. ADD ONE CALENDAR MONTH
# ---------------------------------------------------------

def add_one_calendar_month(value: datetime) -> datetime:
    """
    Adds one calendar month while preserving the time.

    Examples:
    January 31 -> February 28 (or February 29 in a leap year)
    March 31 -> April 30

    The timezone is preserved.
    """

    year = value.year
    month = value.month + 1

    if month > 12:
        month = 1
        year += 1

    last_day = calendar.monthrange(year, month)[1]

    day = min(value.day, last_day)

    return value.replace(
        year=year,
        month=month,
        day=day,
    )


# ---------------------------------------------------------
# 2. FINALISE A SUCCESSFUL PAYMENT
# ---------------------------------------------------------

def finalize_successful_payment(
    db: Session,
    transaction_id,
    capture_id: str,
    provider_event_id: str | None = None,
) -> dict:
    """
    Finalises a verified successful PayPal payment.

    This function must only be called after PayPal's
    capture has been verified.

    It handles:
    - Initial subscription payments.
    - Manual monthly renewals.
    - Duplicate capture/webhook protection.
    - Calendar-aware subscription periods.

    The transaction and subscription are locked while
    the changes are being made.
    """

    if not capture_id:
        raise ValueError("PayPal capture ID is required.")

    try:
        # -------------------------------------------------
        # 1. Lock the payment transaction
        # -------------------------------------------------

        transaction = (
            db.query(PaymentTransaction)
            .filter(
                PaymentTransaction.id == transaction_id,
                PaymentTransaction.provider == "paypal",
            )
            .with_for_update()
            .first()
        )

        if not transaction:
            raise ValueError(
                "Payment transaction was not found."
            )

        # -------------------------------------------------
        # 2. Check whether payment was already completed
        # -------------------------------------------------

        if transaction.status == "completed":
            if transaction.provider_capture_id != capture_id:
                raise ValueError("Transaction already has a different capture ID.")

            subscription = (
                db.query(Subscription)
                .filter(
                    Subscription.id == transaction.subscription_id,
                    Subscription.account_id == transaction.account_id,
                )
                .first()
            )

            if not subscription:
                raise ValueError("Associated subscription was not found.")

            return {
                "status": "already_completed",
                "transaction_id": str(transaction.id),
                "subscription_id": str(subscription.id),
                "payment_status": transaction.status,
                "subscription_status": subscription.status,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
            }

        if transaction.status not in ("pending", "processing"):
            raise ValueError(
                "Transaction is not eligible for completion."
            )

        # -------------------------------------------------
        # 3. Lock the associated subscription
        # -------------------------------------------------

        subscription = (
            db.query(Subscription)
            .filter(
                Subscription.id == transaction.subscription_id,
                Subscription.account_id == transaction.account_id,
            )
            .with_for_update()
            .first()
        )

        if not subscription:
            raise ValueError(
                "Associated subscription was not found."
            )

        # -------------------------------------------------
        # 4. Calculate the new subscription period
        # -------------------------------------------------

        now = datetime.now(timezone.utc)

        existing_period_end = subscription.current_period_end

        if existing_period_end and existing_period_end > now:
            # Early renewal:
            # Start immediately after the existing period ends.

            new_period_start = existing_period_end

        else:
            # Initial payment or expired subscription:
            # Start from the successful payment time.

            new_period_start = now

        new_period_end = add_one_calendar_month(
            new_period_start
        )

        # -------------------------------------------------
        # 5. Complete the payment transaction
        # -------------------------------------------------

        transaction.provider_capture_id = capture_id
        transaction.provider_transaction_id = capture_id
        transaction.status = "completed"

        transaction.completed_at = now
        transaction.failure_message = None

        if provider_event_id:
            transaction.webhook_event_id = provider_event_id

        # -------------------------------------------------
        # 6. Activate and update the subscription
        # -------------------------------------------------

        subscription.status = "active"

        subscription.current_period_start = new_period_start
        subscription.current_period_end = new_period_end

        # -------------------------------------------------
        # 7. Save everything together
        # -------------------------------------------------

        db.commit()

        db.refresh(transaction)
        db.refresh(subscription)

        return {
            "status": "completed",
            "transaction_id": str(transaction.id),
            "subscription_id": str(subscription.id),
            "payment_status": transaction.status,
            "subscription_status": subscription.status,
            "current_period_start": subscription.current_period_start,
            "current_period_end": subscription.current_period_end,
        }

    except Exception:
        db.rollback()
        raise
