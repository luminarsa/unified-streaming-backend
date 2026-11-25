
import asyncio
import logging

from app.db.session import SessionLocal

from app.services.paypal_reconciliation.reconciliation_runner import (
    run_paypal_reconciliation,
)

from app.services.subscription_expiration import (
    expire_due_subscriptions,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# SCHEDULER CONFIGURATION
# ---------------------------------------------------------

PAYPAL_RECONCILIATION_INTERVAL_SECONDS = 60

SUBSCRIPTION_EXPIRATION_INTERVAL_SECONDS = 60


# ---------------------------------------------------------
# PAYPAL RECONCILIATION BACKGROUND LOOP
# ---------------------------------------------------------

async def paypal_reconciliation_loop():
    """
    Runs PayPal reconciliation continuously.

    A new database session is created for every cycle.
    """

    while True:

        db = SessionLocal()

        try:

            logger.info(
                "Starting scheduled PayPal reconciliation."
            )

            result = await run_paypal_reconciliation(db)

            logger.info(
                "Scheduled PayPal reconciliation finished: %s",
                result,
            )

        except asyncio.CancelledError:
            raise

        except Exception:

            db.rollback()

            logger.exception(
                "Scheduled PayPal reconciliation failed."
            )

        finally:
            db.close()

        await asyncio.sleep(
            PAYPAL_RECONCILIATION_INTERVAL_SECONDS
        )


# ---------------------------------------------------------
# SUBSCRIPTION EXPIRATION BACKGROUND LOOP
# ---------------------------------------------------------

async def subscription_expiration_loop():
    """
    Checks for expired subscriptions continuously.

    A new database session is created for every check.
    """

    while True:

        db = SessionLocal()

        try:

            logger.info(
                "Starting scheduled subscription expiration check."
            )

            result = expire_due_subscriptions(db)

            logger.info(
                "Subscription expiration finished: %s",
                result,
            )

        except asyncio.CancelledError:
            raise

        except Exception:

            db.rollback()

            logger.exception(
                "Scheduled subscription expiration failed."
            )

        finally:
            db.close()

        await asyncio.sleep(
            SUBSCRIPTION_EXPIRATION_INTERVAL_SECONDS
        )


# ---------------------------------------------------------
# START BACKGROUND JOBS
# ---------------------------------------------------------

def start_background_jobs() -> list[asyncio.Task]:
    """
    Starts all Lumina background jobs.
    """

    tasks = [
        asyncio.create_task(
            paypal_reconciliation_loop(),
            name="paypal_reconciliation",
        ),
        asyncio.create_task(
            subscription_expiration_loop(),
            name="subscription_expiration",
        ),
    ]

    logger.info(
        "Lumina background jobs started."
    )

    return tasks


# ---------------------------------------------------------
# STOP BACKGROUND JOBS
# ---------------------------------------------------------

async def stop_background_jobs(
    tasks: list[asyncio.Task],
):
    """
    Cancels all background jobs during application shutdown.
    """

    for task in tasks:
        task.cancel()

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, Exception) and not isinstance(
            result,
            asyncio.CancelledError,
        ):
            logger.error(
                "Background task shutdown error: %s",
                result,
            )

    logger.info(
        "Lumina background jobs stopped."
    )
