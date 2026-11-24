
import logging

import httpx
from sqlalchemy.orm import Session

from app.services.paypal_reconciliation.invoice_scanner import (
    scan_paid_invoices,
)

from app.services.paypal_reconciliation.invoice_processor import (
    process_paid_invoice,
)

from app.services.paypal_reconciliation.paypal_client import (
    PAYPAL_API_TIMEOUT_SECONDS,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# RUN ONE RECONCILIATION CYCLE
# ---------------------------------------------------------

async def run_paypal_reconciliation(
    db: Session,
) -> dict:
    """
    Runs one complete PayPal invoice reconciliation cycle.

    1. Connects to PayPal.
    2. Scans for paid invoices.
    3. Retrieves full invoice details.
    4. Processes each invoice against Lumina's database.
    5. Returns a summary of the results.

    This function does not schedule the next run.
    """

    results = {
        "success": True,
        "invoices_found": 0,
        "payments_completed": 0,
        "already_processed": 0,
        "rejected": 0,
        "errors": 0,
        "details": [],
    }

    try:

        # -------------------------------------------------
        # 1. CONNECT TO PAYPAL AND SCAN INVOICES
        # -------------------------------------------------

        async with httpx.AsyncClient(
            timeout=PAYPAL_API_TIMEOUT_SECONDS
        ) as client:

            logger.info(
                "Starting PayPal invoice reconciliation."
            )

            invoices = await scan_paid_invoices(
                client=client
            )

        results["invoices_found"] = len(invoices)

        logger.info(
            "Found %s paid PayPal invoices.",
            len(invoices),
        )

        # -------------------------------------------------
        # 2. PROCESS EACH PAID INVOICE
        # -------------------------------------------------

        for invoice in invoices:

            invoice_id = invoice.get("id")

            try:

                result = process_paid_invoice(
                    db=db,
                    invoice=invoice,
                )

                results["details"].append(result)

                if result.get("processed") is True:

                    results["payments_completed"] += 1

                    logger.info(
                        "Successfully reconciled invoice %s.",
                        invoice_id,
                    )

                elif (
                    result.get("success") is True
                    and result.get("processed") is False
                ):

                    results["already_processed"] += 1

                    logger.info(
                        "Invoice %s was already processed.",
                        invoice_id,
                    )

                else:

                    results["rejected"] += 1

                    logger.warning(
                        "Invoice %s was not processed: %s",
                        invoice_id,
                        result.get("reason"),
                    )

            except Exception as exc:

                db.rollback()

                results["errors"] += 1

                logger.exception(
                    "Error processing PayPal invoice %s: %s",
                    invoice_id,
                    exc,
                )

                results["details"].append({
                    "success": False,
                    "processed": False,
                    "invoice_id": invoice_id,
                    "reason": "Unexpected processing error.",
                })

        # -------------------------------------------------
        # 3. FINISH RECONCILIATION
        # -------------------------------------------------

        logger.info(
            (
                "PayPal reconciliation completed. "
                "Found: %s | Completed: %s | "
                "Already processed: %s | Rejected: %s | "
                "Errors: %s"
            ),
            results["invoices_found"],
            results["payments_completed"],
            results["already_processed"],
            results["rejected"],
            results["errors"],
        )

        if results["errors"] > 0:
            results["success"] = False

        return results

    except Exception:

        db.rollback()

        logger.exception(
            "PayPal reconciliation cycle failed."
        )

        results["success"] = False

        results["errors"] += 1

        return results
