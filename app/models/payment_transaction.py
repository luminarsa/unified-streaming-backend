
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Account that made the payment
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Subscription associated with this payment.
    # Nullable because an initial checkout may fail
    # before a subscription is created.
    subscription_id = Column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Payment method used for the transaction
    payment_method_id = Column(
        UUID(as_uuid=True),
        ForeignKey("payment_methods.id", ondelete="SET NULL"),
        nullable=True,
    )
    encrypted_vault_token = Column(Text)
    # PayPal transaction information
    provider = Column(
        String(50),
        nullable=False,
        default="paypal",
    )

    provider_order_id = Column(String(200))
    provider_capture_id = Column(String(200))
    provider_transaction_id = Column(String(200))

    # Transaction type
    transaction_type = Column(
        String(30),
        nullable=False,
    )

    # Payment amount and currency
    amount = Column(
        Numeric(12, 2),
        nullable=False,
    )

    currency = Column(
        String(3),
        nullable=False,
        default="USD",
    )

    # Transaction status
    status = Column(
        String(30),
        nullable=False,
        default="pending",
    )

    # Billing period associated with this transaction
    billing_period_start = Column(DateTime(timezone=True))
    billing_period_end = Column(DateTime(timezone=True))

    # PayPal failure or response information
    failure_code = Column(String(100))
    failure_message = Column(Text)

    # PayPal webhook event identifier
    webhook_event_id = Column(String(200))

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    completed_at = Column(DateTime(timezone=True))

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "amount >= 0",
            name="check_payment_transaction_amount",
        ),
        CheckConstraint(
            "transaction_type IN ('initial', 'renewal', 'plan_change', 'refund')",
            name="check_payment_transaction_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'cancelled', 'refunded')",
            name="check_payment_transaction_status",
        ),
        UniqueConstraint(
            "provider_capture_id",
            name="uq_payment_transaction_capture_id",
        ),
        UniqueConstraint(
            "webhook_event_id",
            name="uq_payment_transaction_webhook_event",
        ),
    )
