
import logging
import sys

from app.db.session import SessionLocal
from app.services.cache_refresh_service import refresh_lumina_cache


# ---------------------------------------------------------
# LOGGING CONFIGURATION
# ---------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# CACHE REFRESH RUNNER
# ---------------------------------------------------------

def main():

    logger.info("LUMINA CACHE REFRESH JOB STARTED")

    db = SessionLocal()

    try:

        result = refresh_lumina_cache(db)

        logger.info("LUMINA CACHE REFRESH RESULT: %s", result)

        if result.get("status") not in ("success", "partial_success"):
            logger.error("LUMINA CACHE REFRESH JOB FAILED")
            sys.exit(1)

        logger.info("LUMINA CACHE REFRESH JOB COMPLETED")

    except Exception:

        logger.exception("LUMINA CACHE REFRESH JOB CRASHED")
        sys.exit(1)

    finally:

        db.close()
        logger.info("DATABASE SESSION CLOSED")


if __name__ == "__main__":
    main()
