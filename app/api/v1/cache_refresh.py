
import logging
import os
import secrets

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status

from app.db.session import SessionLocal
from app.services.cache_refresh_service import refresh_lumina_cache


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cache-refresh",
    tags=["Cache Refresh"],
)


# ---------------------------------------------------------
# BACKGROUND CACHE REFRESH
# ---------------------------------------------------------

def run_cache_refresh_background():

    logger.info("CACHE REFRESH BACKGROUND TASK STARTED")

    db = SessionLocal()

    try:

        result = refresh_lumina_cache(db)

        logger.info(
            "CACHE REFRESH BACKGROUND TASK RESULT | %s",
            result,
        )

        if result.get("status") not in (
            "success",
            "partial_success",
        ):
            logger.error(
                "CACHE REFRESH BACKGROUND TASK COMPLETED WITH ERRORS"
            )

        else:
            logger.info(
                "CACHE REFRESH BACKGROUND TASK COMPLETED"
            )

    except Exception:

        logger.exception(
            "CACHE REFRESH BACKGROUND TASK CRASHED"
        )

    finally:

        db.close()

        logger.info(
            "CACHE REFRESH BACKGROUND DATABASE SESSION CLOSED"
        )


# ---------------------------------------------------------
# PROTECTED REFRESH ENDPOINT
# ---------------------------------------------------------

@router.post(
    "/trigger",
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_cache_refresh(
    background_tasks: BackgroundTasks,
    x_cache_refresh_token: str = Header(
        default="",
        alias="X-Cache-Refresh-Token",
    ),
):

    expected_token = os.getenv("CACHE_REFRESH_SECRET")

    # Fail closed if the secret has not been configured.
    if not expected_token:
        logger.error(
            "CACHE REFRESH | CACHE_REFRESH_SECRET is not configured"
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache refresh service is not configured.",
        )

    # Validate the request token.
    if not secrets.compare_digest(
        x_cache_refresh_token,
        expected_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid cache refresh token.",
        )

    # Start the refresh without keeping the HTTP request open.
    background_tasks.add_task(
        run_cache_refresh_background
    )

    logger.info(
        "CACHE REFRESH | Authenticated external trigger received"
    )

    return {
        "status": "accepted",
        "message": "Cache refresh has been scheduled.",
    }
