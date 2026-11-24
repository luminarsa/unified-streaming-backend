
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import calendar

import httpx
from sqlalchemy.orm import Session

from app.models.payment_transaction import PaymentTransaction
from app.models.commercial import Subscription, Plan


# ---------------------------------------------------------
# SUBSCRIPTION PERIOD CALCULATION
# ---------------------------------------------------------

def calculate_subscription_period(
    start_date: datetime,
    billing_interval: str,
) -> datetime:
    """
    Calculates the end date of a subscription period.

    Supported intervals:
    - Monthly
    - Quarterly
    - Yearly / Annual
    - Weekly
    """

    interval = (billing_interval or "").strip().lower()

    if interval in ("monthly", "month"):
        months_to_add = 1

    elif interval in ("quarterly", "quarter"):
        months_to_add = 3

    elif interval in ("yearly", "annual", "annually", "year"):
        months_to_add = 12

    elif interval in ("weekly", "week"):
        from datetime import timedelta
        return start_date + timedelta(days=7)

    else:
        raise ValueError(
            f"Unsupported billing interval: {billing_interval}"
        )

    total_months = (
        start_date.year * 12
        + start_date.month - 1
        + months_to_add
    )

    new_year = total_months // 12
    new_month = total_months % 12 + 1

    last_day = calendar.monthrange(
        new_year,
        new_month,
    )[1]

    new_day = min(start_date.day, last_day)

    return start_date.replace(
        year=new_year,
        month=new_month,
        day=new_day,
    )


# ---------------------------------------------------------
# MONEY VALIDATION
# ---------------------------------------------------------

def get_decimal_amount(value) -> Decimal:
    """
    Converts a monetary value into Decimal safely.
    """

    try:
        return Decimal(str(value))

    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            f"Invalid monetary amount: {value}"
        )


# ---------------------------------------------------------
# PAYMENT DATE EXTRACTION
# ---------------------------------------------------------

def extract_payment_date(invoice: dict) -> datetime:
    """
    Extracts the payment date from the invoice payment
    transactions.

    Falls back to the current UTC time if PayPal does
    not provide a payment date.
    """

    payments = invoice.get("payments") or {}

    transactions = payments.get("transactions") or []

    for payment in reversed(transactions):

        payment_date = payment.get("payment_date")

        if not payment_date:
            continue

        try:
            parsed_date = datetime.fromisoformat(
                payment_date.replace("Z", "+00:00")
            )

            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(
                    tzinfo=timezone.utc
                )

            return parsed_date

        except (ValueError, TypeError):
            continue

    return datetime.now(timezone.utc)


# ---------------------------------------------------------
# PROCESS PAID PAYPAL INVOICE
# ---------------------------------------------------------

def process_paid_invoice(
    db: Session,
    invoice: dict,
) -> dict:
    """
    Verifies a paid PayPal invoice against an existing
    Lumina payment transaction.

    If all checks pass:
    - Completes the payment transaction.
    - Activates the associated subscription.
    - Sets the subscription period.
    - Records payment details.

    This function is idempotent and uses database row
    locking to protect against overlapping processing.
    """

    invoice_id = invoice.get("id")

    if not invoice_id:
        return {
            "success": False,
            "processed": False,
            "reason": "Invoice ID is missing.",
        }

    # -----------------------------------------------------
    # 1. VERIFY PAYPAL INVOICE STATUS
    # -----------------------------------------------------

    if invoice.get("status") != "PAID":
        return {
            "success": False,
            "processed": False,
            "reason": "Invoice is not fully paid.",
            "invoice_id": invoice_id,
        }

    # -----------------------------------------------------
    # 2. FIND EXISTING PAYMENT TRANSACTION
    # -----------------------------------------------------

    try:
        transaction = (
            db.query(PaymentTransaction)
            .filter(
                PaymentTransaction.provider == "paypal",
                PaymentTransaction.provider_invoice_id == invoice_id,
            )
            .with_for_update()
            .first()
        )

        if not transaction:
            return {
                "success": False,
                "processed": False,
                "reason": "No matching Lumina payment transaction.",
                "invoice_id": invoice_id,
            }

        # -------------------------------------------------
        # 3. CHECK TRANSACTION STATUS
        # -------------------------------------------------

        if transaction.status == "completed":
            return {
                "success": True,
                "processed": False,
                "reason": "Transaction was already completed.",
                "invoice_id": invoice_id,
                "transaction_id": str(transaction.id),
            }

        if transaction.status != "pending":
            return {
                "success": False,
                "processed": False,
                "reason": (
                    f"Transaction status is {transaction.status}; "
                    "only pending transactions can be processed."
                ),
                "invoice_id": invoice_id,
            }

        if transaction.transaction_type not in (
            "initial",
            "renewal",
            "plan_change",
        ):
            return {
                "success": False,
                "processed": False,
                "reason": "Unsupported transaction type.",
                "invoice_id": invoice_id,
            }

        if not transaction.subscription_id:
            return {
                "success": False,
                "processed": False,
                "reason": "Transaction has no subscription ID.",
                "invoice_id": invoice_id,
            }

        # -------------------------------------------------
        # 4. VERIFY SUBSCRIPTION REFERENCE
        # -------------------------------------------------

        detail = invoice.get("detail") or {}

        paypal_reference = detail.get("reference")

        if not paypal_reference:
            return {
                "success": False,
                "processed": False,
                "reason": "PayPal invoice reference is missing.",
                "invoice_id": invoice_id,
            }

        if paypal_reference != str(transaction.subscription_id):
            return {
                "success": False,
                "processed": False,
                "reason": "Invoice subscription reference mismatch.",
                "invoice_id": invoice_id,
            }

        # -------------------------------------------------
        # 5. VERIFY INVOICE AMOUNT AND CURRENCY
        # -------------------------------------------------

        invoice_amount = invoice.get("amount") or {}

        invoice_currency = (
            invoice_amount.get("currency_code")
            or detail.get("currency_code")
        )

        invoice_total = invoice_amount.get("value")

        if invoice_total is None or not invoice_currency:
            return {
                "success": False,
                "processed": False,
                "reason": "Invoice total or currency is missing.",
                "invoice_id": invoice_id,
            }

        expected_amount = get_decimal_amount(
            transaction.amount
        )

        actual_amount = get_decimal_amount(
            invoice_total
        )

        if actual_amount != expected_amount:
            return {
                "success": False,
                "processed": False,
                "reason": "Invoice amount does not match Lumina transaction.",
                "invoice_id": invoice_id,
                "expected_amount": str(expected_amount),
                "actual_amount": str(actual_amount),
            }

        if invoice_currency.upper() != transaction.currency.upper():
            return {
                "success": False,
                "processed": False,
                "reason": "Invoice currency does not match Lumina transaction.",
                "invoice_id": invoice_id,
            }

        # -------------------------------------------------
        # 6. VERIFY ACTUAL AMOUNT PAID
        # -------------------------------------------------

        payments = invoice.get("payments") or {}

        paid_amount = payments.get("paid_amount") or {}

        paid_value = paid_amount.get("value")

        paid_currency = paid_amount.get("currency_code")

        if paid_value is None or not paid_currency:
            return {
                "success": False,
                "processed": False,
                "reason": "PayPal payment amount is missing.",
                "invoice_id": invoice_id,
            }

        actual_paid_amount = get_decimal_amount(
            paid_value
        )

        if actual_paid_amount != expected_amount:
            return {
                "success": False,
                "processed": False,
                "reason": "Total amount paid does not match transaction amount.",
                "invoice_id": invoice_id,
                "expected_amount": str(expected_amount),
                "actual_paid_amount": str(actual_paid_amount),
            }

        if paid_currency.upper() != transaction.currency.upper():
            return {
                "success": False,
                "processed": False,
                "reason": "Paid currency does not match transaction currency.",
                "invoice_id": invoice_id,
            }

        # -------------------------------------------------
        # 7. FIND AND LOCK SUBSCRIPTION
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
            return {
                "success": False,
                "processed": False,
                "reason": "Associated Lumina subscription was not found.",
                "invoice_id": invoice_id,
            }

        if subscription.status not in ("pending", "active", "expired"):
            return {
                "success": False,
                "processed": False,
                "reason": "Subscription has an unsupported status.",
                "invoice_id": invoice_id,
            }

        # -------------------------------------------------
        # 8. FIND ASSOCIATED PLAN
        # -------------------------------------------------

        plan = (
            db.query(Plan)
            .filter(
                Plan.id == subscription.plan_id
            )
            .first()
        )

        if not plan:
            return {
                "success": False,
                "processed": False,
                "reason": "Subscription plan was not found.",
                "invoice_id": invoice_id,
            }

        # -------------------------------------------------
        # 9. CALCULATE SUBSCRIPTION PERIOD
        # -------------------------------------------------

        payment_date = extract_payment_date(invoice)

        # If this is a renewal and the existing subscription
        # has not expired, extend from its current end date.
        if (
            transaction.transaction_type == "renewal"
            and subscription.status == "active"
            and subscription.current_period_end
            and subscription.current_period_end > payment_date
        ):
            period_start = subscription.current_period_end

        else:
            period_start = payment_date

        period_end = calculate_subscription_period(
            start_date=period_start,
            billing_interval=plan.billing_interval,
        )

        # -------------------------------------------------
        # 10. UPDATE PAYMENT TRANSACTION
        # -------------------------------------------------

        payment_transactions = payments.get("transactions") or []

        if payment_transactions:
            latest_payment = payment_transactions[-1]

            payment_id = latest_payment.get("payment_id")

            if payment_id:
                transaction.provider_transaction_id = payment_id

        transaction.status = "completed"

        transaction.provider_invoice_status = "PAID"

        transaction.provider_payment_date = payment_date

        transaction.last_reconciled_at = datetime.now(
            timezone.utc
        )

        transaction.completed_at = datetime.now(
            timezone.utc
        )

        transaction.billing_period_start = period_start

        transaction.billing_period_end = period_end

        # -------------------------------------------------
        # 11. ACTIVATE SUBSCRIPTION
        # -------------------------------------------------

        subscription.status = "active"

        subscription.current_period_start = period_start

        subscription.current_period_end = period_end

        subscription.next_billing_at = period_end

        # -------------------------------------------------
        # 12. COMMIT BOTH UPDATES TOGETHER
        # -------------------------------------------------

        db.commit()

        return {
            "success": True,
            "processed": True,
            "reason": "Payment verified and subscription activated.",
            "invoice_id": invoice_id,
            "transaction_id": str(transaction.id),
            "subscription_id": str(subscription.id),
            "account_id": str(subscription.account_id),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }

    except Exception:
        db.rollback()
        raise
