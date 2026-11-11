
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.paypal import (
    PayPalError,
    verify_webhook_signature,
)
from app.services.paypal_webhook_events import (
    store_verified_webhook_event,
    process_webhook_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/paypal",
    tags=["PayPal Webhooks"],
)


@router.post("/webhook")
async def receive_paypal_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    # ---------------------------------------------------------
    # 1. Read and validate the incoming JSON payload
    # ---------------------------------------------------------

    try:
        webhook_event = await request.json()

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook JSON payload.",
        )

    if not isinstance(webhook_event, dict):
        raise HTTPException(
            status_code=400,
            detail="Webhook payload must be a JSON object.",
        )

    event_id = webhook_event.get("id")
    event_type = webhook_event.get("event_type")

    if not isinstance(event_id, str) or not event_id.strip():
        raise HTTPException(
            status_code=400,
            detail="PayPal webhook event ID is missing or invalid.",
        )

    if not isinstance(event_type, str) or not event_type.strip():
        raise HTTPException(
            status_code=400,
            detail="PayPal webhook event type is missing or invalid.",
        )

    # ---------------------------------------------------------
    # 2. Verify the webhook signature with PayPal
    # ---------------------------------------------------------

    try:
        is_verified = await verify_webhook_signature(
            headers=request.headers,
            webhook_event=webhook_event,
        )

    except PayPalError:
        logger.exception(
            "PayPal webhook verification service failed. Event ID: %s",
            event_id,
        )

        raise HTTPException(
            status_code=503,
            detail="Unable to verify PayPal webhook. Please retry.",
        )

    except Exception:
        logger.exception(
            "Unexpected error verifying PayPal webhook. Event ID: %s",
            event_id,
        )

        raise HTTPException(
            status_code=503,
            detail="Unexpected webhook verification error. Please retry.",
        )

    if not is_verified:
        logger.warning(
            "PayPal webhook signature verification failed. Event ID: %s",
            event_id,
        )

        raise HTTPException(
            status_code=400,
            detail="PayPal webhook signature verification failed.",
        )

    # ---------------------------------------------------------
    # 3. Store the verified event in PostgreSQL
    # ---------------------------------------------------------

    try:
        storage_result = store_verified_webhook_event(
            db=db,
            webhook_event=webhook_event,
        )

    except Exception:
        db.rollback()

        logger.exception(
            "Failed to store verified PayPal webhook. Event ID: %s",
            event_id,
        )

        raise HTTPException(
            status_code=503,
            detail="Unable to store PayPal webhook. Please retry.",
        )

    is_duplicate = storage_result["duplicate"]

    if is_duplicate:
        logger.info(
            "Duplicate PayPal webhook received. "
            "Checking whether processing is still required. "
            "Event ID: %s, Type: %s",
            event_id,
            event_type,
        )

    else:
        logger.info(
            "PayPal webhook successfully verified and stored. "
            "Event ID: %s, Type: %s",
            event_id,
            event_type,
        )

    # ---------------------------------------------------------
    # 4. Process the stored event
    # ---------------------------------------------------------

    try:
        processing_result = await process_webhook_event(
            db=db,
            provider_event_id=event_id,
        )

    except Exception:
        db.rollback()

        logger.exception(
            "Failed to process PayPal webhook. "
            "PayPal will be asked to retry. Event ID: %s, Type: %s",
            event_id,
            event_type,
        )

        raise HTTPException(
            status_code=503,
            detail="Webhook processing failed. Please retry.",
        )

    processing_status = processing_result.get(
        "status",
        "received",
    )

    logger.info(
        "PayPal webhook processing result. "
        "Event ID: %s, Type: %s, Status: %s",
        event_id,
        event_type,
        processing_status,
    )

    # ---------------------------------------------------------
    # 5. Acknowledge the webhook
    # ---------------------------------------------------------

    return {
        "status": processing_status,
        "verified": True,
        "duplicate": is_duplicate,
        "event_id": event_id,
        "event_type": event_type,
        "processing": processing_result,
    }
