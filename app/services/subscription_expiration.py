
import logging

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.commercial import Subscription


logger = logging.getLogger(__name__)


def expire_due_subscriptions(db: Session) -> dict:
    """
    Expires active subscriptions whose paid period has ended.

    Only subscriptions satisfying both conditions are updated:
    - status is active
    - current_period_end is less than or equal to current UTC time
    """

    now = datetime.now(timezone.utc)

    try:
        expired_subscriptions = (
            db.query(Subscription)
            .filter(
                Subscription.status == "active",
                Subscription.current_period_end.isnot(None),
                Subscription.current_period_end <= now,
            )
            .with_for_update()
            .all()
        )

        expired_count = len(expired_subscriptions)

        for subscription in expired_subscriptions:
            subscription.status = "expired"

        db.commit()

        logger.info(
            "Subscription expiration completed. Expired: %s",
            expired_count,
        )

        return {
            "success": True,
            "expired_count": expired_count,
            "checked_at": now.isoformat(),
        }

    except Exception:
        db.rollback()

        logger.exception(
            "Subscription expiration process failed."
        )

        raise
