from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from app.models.paypal_webhook_event import PayPalWebhookEvent
from app.models.commercial import Subscription
from app.models.payment_transaction import PaymentTransaction
from app.services import paypal

def store_verified_webhook_event(
    db: Session,
    webhook_event: dict,
) -> dict:
    """
    Store a PayPal webhook event after its signature has been verified.

    Returns whether the event was newly stored or was already received.
    """

    event_id = webhook_event.get("id")
    event_type = webhook_event.get("event_type")

    if not event_id or not event_type:
        raise ValueError("PayPal webhook event ID or event type is missing.")

    resource = webhook_event.get("resource") or {}

    if not isinstance(resource, dict):
        resource = {}

    statement = (
        insert(PayPalWebhookEvent)
        .values(
            provider_event_id=event_id,
            event_type=event_type,
            resource_type=webhook_event.get("resource_type"),
            resource_id=resource.get("id"),
            payload=webhook_event,
            status="received",
            processing_attempts=0,
        )
        .on_conflict_do_nothing(
            index_elements=["provider_event_id"]
        )
        .returning(PayPalWebhookEvent.id)
    )

    try:
        inserted_id = db.execute(statement).scalar_one_or_none()

        if inserted_id is not None:
            db.commit()

            return {
                "event_id": event_id,
                "stored": True,
                "duplicate": False,
            }

        # The event already exists. Retrieve its existing record.
        existing_event = db.execute(
            select(PayPalWebhookEvent).where(
                PayPalWebhookEvent.provider_event_id == event_id
            )
        ).scalar_one_or_none()

        if existing_event is None:
            raise RuntimeError(
                "PayPal webhook event already exists, but could not be retrieved."
            )

        db.commit()

        return {
            "event_id": event_id,
            "stored": False,
            "duplicate": True,
        }

    except Exception:
        db.rollback()
        raise


async def process_capture_completed_event(
    db: Session,
    provider_event_id: str,
) -> dict:
    """
    Processes a verified PAYMENT.CAPTURE.COMPLETED event.

    Verifies the PayPal order, transaction, subscription,
    capture ID, amount and currency before completing
    the local payment transaction.
    """

    # -----------------------------------------------------
    # 1. Retrieve the stored webhook event
    # -----------------------------------------------------

    event = (
        db.query(PayPalWebhookEvent)
        .filter(
            PayPalWebhookEvent.provider_event_id == provider_event_id
        )
        .with_for_update()
        .first()
    )

    if not event:
        raise ValueError("Webhook event was not found.")

    if event.status == "processed":
        return {
            "status": "already_processed",
            "event_id": provider_event_id,
        }

    if event.event_type != "PAYMENT.CAPTURE.COMPLETED":
        raise ValueError("This processor only accepts completed capture events.")

    resource = event.payload.get("resource") or {}

    if not isinstance(resource, dict):
        raise ValueError("PayPal capture resource is invalid.")

    capture_id = resource.get("id")

    related_ids = (
        resource.get("supplementary_data", {})
        .get("related_ids", {})
    )

    order_id = related_ids.get("order_id")

    if not capture_id or not order_id:
        raise ValueError(
            "PayPal capture event is missing its capture or order ID."
        )

    # -----------------------------------------------------
    # 2. Mark event as processing
    # -----------------------------------------------------

    event.status = "processing"
    event.processing_attempts += 1
    event.last_error = None

    db.commit()

    # -----------------------------------------------------
    # 3. Retrieve the authoritative PayPal order
    # -----------------------------------------------------

    try:
        order = await paypal.get_order(order_id)

    except paypal.PayPalError:
        db.rollback()

        failed_event = (
            db.query(PayPalWebhookEvent)
            .filter(
                PayPalWebhookEvent.provider_event_id == provider_event_id
            )
            .first()
        )

        if failed_event:
            failed_event.status = "failed"
            failed_event.last_error = (
                "Unable to retrieve the related PayPal order."
            )
            db.commit()

        raise

    # -----------------------------------------------------
    # 4. Find our local payment transaction
    # -----------------------------------------------------

    transaction = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.provider == "paypal",
            PaymentTransaction.provider_order_id == order_id,
        )
        .with_for_update()
        .first()
    )

    if not transaction:
        raise ValueError(
            "No local payment transaction matches this PayPal order."
        )

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
            "The subscription associated with this payment was not found."
        )

    # -----------------------------------------------------
    # 5. Verify the order belongs to this subscription
    # -----------------------------------------------------

    purchase_units = order.get("purchase_units", [])

    if not purchase_units:
        raise ValueError("PayPal order has no purchase units.")

    purchase_unit = purchase_units[0]

    subscription_reference = (
        purchase_unit.get("reference_id")
        or purchase_unit.get("custom_id")
    )

    if subscription_reference != str(subscription.id):
        raise ValueError(
            "PayPal order does not match the local subscription."
        )

    # -----------------------------------------------------
    # 6. Verify the capture details from the webhook
    # -----------------------------------------------------

    if resource.get("status") != "COMPLETED":
        raise ValueError("PayPal capture is not completed.")

    capture_amount = resource.get("amount") or {}

    try:
        actual_amount = Decimal(str(capture_amount.get("value")))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("PayPal capture amount is invalid.")

    actual_currency = capture_amount.get("currency_code")

    if (
        actual_amount != transaction.amount
        or actual_currency != transaction.currency
    ):
        raise ValueError(
            "PayPal capture amount or currency does not match the transaction."
        )

    # -----------------------------------------------------
    # 7. Confirm capture exists in the retrieved order
    # -----------------------------------------------------

    order_payments = purchase_unit.get("payments", {})
    order_captures = order_payments.get("captures", [])

    matching_capture = next(
        (
            capture
            for capture in order_captures
            if capture.get("id") == capture_id
        ),
        None,
    )

    if not matching_capture:
        raise ValueError(
            "Capture ID was not found in the retrieved PayPal order."
        )

    if matching_capture.get("status") != "COMPLETED":
        raise ValueError(
            "The retrieved PayPal capture is not completed."
        )

    # -----------------------------------------------------
    # 8. Prevent conflicting or duplicate capture records
    # -----------------------------------------------------

    if transaction.provider_capture_id:
        if transaction.provider_capture_id != capture_id:
            raise ValueError(
                "Transaction already contains a different capture ID."
            )

    if transaction.status == "completed":
        if transaction.provider_capture_id != capture_id:
            raise ValueError(
                "Completed transaction has a conflicting capture ID."
            )

    elif transaction.status not in ("pending", "processing"):
        raise ValueError(
            "Transaction is not eligible for completion."
        )

    # -----------------------------------------------------
    # 9. Complete the transaction and activate subscription
    # -----------------------------------------------------

    now = datetime.now(timezone.utc)

    transaction.provider_capture_id = capture_id
    transaction.provider_transaction_id = capture_id
    transaction.webhook_event_id = provider_event_id
    transaction.status = "completed"
    transaction.completed_at = transaction.completed_at or now
    transaction.failure_message = None

    subscription.status = "active"

    if subscription.current_period_start is None:
        subscription.current_period_start = now

    event.status = "processed"
    event.processed_at = now
    event.last_error = None

    db.commit()

    return {
        "status": "processed",
        "event_id": provider_event_id,
        "capture_id": capture_id,
        "transaction_id": str(transaction.id),
        "subscription_id": str(subscription.id),
        "payment_status": transaction.status,
        "subscription_status": subscription.status,
    }


async def process_webhook_event(
    db: Session,
    provider_event_id: str,
) -> dict:
    """
    Dispatches a stored webhook event to its processor.

    Failed events can be retried.
    Already processed events are not processed again.
    """

    event = (
        db.query(PayPalWebhookEvent)
        .filter(
            PayPalWebhookEvent.provider_event_id == provider_event_id
        )
        .first()
    )

    if not event:
        raise ValueError("Webhook event was not found.")

    if event.status == "processed":
        return {
            "status": "already_processed",
            "event_id": provider_event_id,
        }

    if event.event_type != "PAYMENT.CAPTURE.COMPLETED":
        return {
            "status": "not_supported_yet",
            "event_id": provider_event_id,
            "event_type": event.event_type,
        }

    try:
        return await process_capture_completed_event(
            db=db,
            provider_event_id=provider_event_id,
        )

    except Exception as exc:
        db.rollback()

        # Record the failure so the event can be retried.
        failed_event = (
            db.query(PayPalWebhookEvent)
            .filter(
                PayPalWebhookEvent.provider_event_id == provider_event_id
            )
            .first()
        )

        if failed_event and failed_event.status != "processed":
            failed_event.status = "failed"
            failed_event.last_error = str(exc)[:2000]

            db.commit()

        raise