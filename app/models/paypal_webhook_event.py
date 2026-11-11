
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class PayPalWebhookEvent(Base):
    __tablename__ = "paypal_webhook_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # PayPal's unique event ID. Prevents duplicate event records.
    provider_event_id = Column(
        String(200),
        nullable=False,
    )

    event_type = Column(
        String(150),
        nullable=False,
        index=True,
    )

    resource_type = Column(String(100))
    resource_id = Column(String(200))

    # Store the original verified event for auditing and retries.
    payload = Column(
        JSONB,
        nullable=False,
    )

    # received -> processing -> processed
    # A failed event can be retried after investigation.
    status = Column(
        String(30),
        nullable=False,
        default="received",
    )

    processing_attempts = Column(
        Integer,
        nullable=False,
        default=0,
    )

    last_error = Column(Text)

    received_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    processed_at = Column(DateTime(timezone=True))

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "provider_event_id",
            name="uq_paypal_webhook_event_provider_id",
        ),
        CheckConstraint(
            "status IN ('received', 'processing', 'processed', 'failed')",
            name="check_paypal_webhook_event_status",
        ),
        CheckConstraint(
            "processing_attempts >= 0",
            name="check_paypal_webhook_event_attempts",
        ),
    )
