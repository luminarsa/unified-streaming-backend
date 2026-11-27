
import logging

import calendar

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models.commercial import (
    Card2CryptoPayment,
    Subscription,
)
from app.models.payment_transaction import PaymentTransaction

logger = logging.getLogger(__name__)


def add_one_month(value: datetime) -> datetime:
    """
    Add one calendar month while preserving the time.

    If the next month has fewer days, use its final day.
    Example: 31 January becomes 28 February (or 29 in a leap year).
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


def process_card2crypto_payment(
    db: Session,
    payment_reference: str,
    value_coin: str,
    coin: str,
    txid_in: str,
    txid_out: str,
    value_forwarded_coin: str | None = None,
) -> dict:
    """
    Complete a Card2Crypto payment and activate its subscription.

    The caller must validate the callback authentication token and
    receiving address before calling this function.
    """

    try:
        received_amount = Decimal(str(value_coin))

        if not received_amount.is_finite() or received_amount <= 0:
            raise ValueError("Invalid received payment amount.")

        forwarded_amount = None

        if value_forwarded_coin is not None:
            forwarded_amount = Decimal(str(value_forwarded_coin))

            if (
                not forwarded_amount.is_finite()
                or forwarded_amount < 0
            ):
                raise ValueError("Invalid forwarded payment amount.")

        # --------------------------------------------------
        # 1. Lock the Card2Crypto payment record.
        # --------------------------------------------------

        card_payment = (
            db.query(Card2CryptoPayment)
            .filter(
                Card2CryptoPayment.payment_reference
                == payment_reference
            )
            .with_for_update()
            .first()
        )

        if not card_payment:
            raise ValueError("Card2Crypto payment was not found.")

        # --------------------------------------------------
        # 2. Lock the associated Lumina transaction.
        # --------------------------------------------------

        transaction = (
            db.query(PaymentTransaction)
            .filter(
                PaymentTransaction.id
                == card_payment.payment_transaction_id
            )
            .with_for_update()
            .first()
        )

        if not transaction:
            raise ValueError("Payment transaction was not found.")

        if transaction.provider != "card2crypto":
            raise ValueError("Payment transaction provider mismatch.")

        # --------------------------------------------------
        # 3. Handle duplicate callbacks.
        # --------------------------------------------------

        if (
            card_payment.status == "paid"
            and transaction.status == "completed"
        ):
            db.commit()

            return {
                "success": True,
                "message": "Payment was already processed.",
                "payment_reference": payment_reference,
                "payment_status": "paid",
                "subscription_status": "active",
                "already_processed": True,
            }

        if (
            card_payment.status != "pending"
            or transaction.status != "pending"
        ):
            raise ValueError(
                "This payment is not in a processable state."
            )

        # --------------------------------------------------
        # 4. Validate the received amount.
        # --------------------------------------------------

        expected_amount = Decimal(
            str(card_payment.usd_amount)
        )

        # Allow a two-cent difference for provider rounding.
        tolerance = Decimal("0.02")

        if abs(received_amount - expected_amount) > tolerance:
            card_payment.status = "failed"
            transaction.status = "failed"
            transaction.failure_code = "PAYMENT_AMOUNT_MISMATCH"
            transaction.failure_message = (
                f"Expected USD {expected_amount}; "
                f"received USD {received_amount}."
            )

            db.commit()

            logger.warning(
                "Card2Crypto payment amount mismatch. "
                "Reference: %s, expected: %s, received: %s",
                payment_reference,
                expected_amount,
                received_amount,
            )

            raise ValueError(
                "The received payment amount does not match the checkout amount."
            )

        # --------------------------------------------------
        # 5. Prevent reuse of transaction hashes.
        # --------------------------------------------------

        duplicate_txid = (
            db.query(Card2CryptoPayment)
            .filter(
                Card2CryptoPayment.id != card_payment.id,
                (
                    (Card2CryptoPayment.txid_in == txid_in)
                    | (Card2CryptoPayment.txid_out == txid_out)
                ),
            )
            .first()
        )

        if duplicate_txid:
            raise ValueError(
                "This blockchain transaction has already been processed."
            )

        # --------------------------------------------------
        # 6. Lock the subscription.
        # --------------------------------------------------

        subscription = (
            db.query(Subscription)
            .filter(
                Subscription.id == transaction.subscription_id
            )
            .with_for_update()
            .first()
        )

        if not subscription:
            raise ValueError("Associated subscription was not found.")

        if subscription.status not in ("pending", "active"):
            raise ValueError(
                "The associated subscription cannot be activated."
            )

        # --------------------------------------------------
        # 7. Calculate the monthly subscription period.
        # --------------------------------------------------

        now = datetime.now(timezone.utc)

        period_start = now
        period_end = add_one_month(now)

        # --------------------------------------------------
        # 8. Complete the Card2Crypto payment record.
        # --------------------------------------------------

        card_payment.status = "paid"
        card_payment.coin = coin
        card_payment.value_coin = received_amount
        card_payment.value_forwarded_coin = forwarded_amount
        card_payment.txid_in = txid_in
        card_payment.txid_out = txid_out
        card_payment.callback_received_at = now
        card_payment.paid_at = now

        # --------------------------------------------------
        # 9. Complete the Lumina payment transaction.
        # --------------------------------------------------

        transaction.status = "completed"
        transaction.provider_payment_date = now
        transaction.completed_at = now

        transaction.billing_period_start = period_start
        transaction.billing_period_end = period_end

        # --------------------------------------------------
        # 10. Activate the subscription.
        # --------------------------------------------------

        subscription.status = "active"
        subscription.provider = "card2crypto"
        subscription.current_period_start = period_start
        subscription.current_period_end = period_end
        subscription.next_billing_at = period_end
        subscription.grace_period_ends_at = None

        # --------------------------------------------------
        # 11. Commit everything together.
        # --------------------------------------------------

        db.commit()

        logger.info(
            "Card2Crypto payment completed successfully. "
            "Reference: %s, subscription: %s",
            payment_reference,
            subscription.id,
        )

        return {
            "success": True,
            "message": "Card2Crypto payment processed successfully.",
            "payment_reference": payment_reference,
            "payment_status": "paid",
            "subscription_id": str(subscription.id),
            "subscription_status": "active",
            "current_period_start": period_start.isoformat(),
            "current_period_end": period_end.isoformat(),
            "already_processed": False,
        }

    except Exception:
        db.rollback()
        logger.exception(
            "Card2Crypto payment processing failed. Reference: %s",
            payment_reference,
        )
        raise
