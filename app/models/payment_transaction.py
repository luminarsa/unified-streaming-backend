
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

    # Account that made the payment.
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Subscription associated with this payment.
    subscription_id = Column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    payment_method_id = Column(
        UUID(as_uuid=True),
        ForeignKey("payment_methods.id", ondelete="SET NULL"),
        nullable=True,
    )

    encrypted_vault_token = Column(Text)

    # Payment provider.
    provider = Column(
        String(50),
        nullable=False,
        default="paypal",
    )

    # Legacy PayPal Orders/Capture fields.
    # Retained for historical transactions.
    provider_order_id = Column(String(200))
    provider_capture_id = Column(String(200))
    provider_transaction_id = Column(String(200))

    # New PayPal Invoicing fields.
    provider_invoice_id = Column(String(200), unique=True)
    provider_invoice_number = Column(String(100))
    provider_invoice_url = Column(Text)
    provider_invoice_status = Column(String(50))
    # Identifies one checkout attempt so retries cannot
    # accidentally create duplicate subscription payments.
    idempotency_key = Column(String(100), nullable=True)
    # Unique Lumina transaction reference is this row's UUID (id).

    # Payment reconciliation information.
    provider_payment_date = Column(DateTime(timezone=True))
    last_reconciled_at = Column(DateTime(timezone=True))

    # Invoice reminder management.
    reminder_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    next_reminder_at = Column(DateTime(timezone=True))
    invoice_expires_at = Column(DateTime(timezone=True))

    # Transaction type.
    transaction_type = Column(
        String(30),
        nullable=False,
    )

    # Payment amount and currency.
    amount = Column(
        Numeric(12, 2),
        nullable=False,
    )

    currency = Column(
        String(3),
        nullable=False,
        default="USD",
    )

    # Lumina transaction status.
    status = Column(
        String(30),
        nullable=False,
        default="pending",
    )

    # Billing period associated with this transaction.
    billing_period_start = Column(DateTime(timezone=True))
    billing_period_end = Column(DateTime(timezone=True))

    # PayPal failure or response information.
    failure_code = Column(String(100))
    failure_message = Column(Text)

    # Retained for legacy webhook records.
    webhook_event_id = Column(String(200))

    # Timestamps.
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
        UniqueConstraint(
            "account_id",
            "idempotency_key",
            name="uq_payment_transaction_account_idempotency",
        ),
        CheckConstraint(
            "transaction_type IN ('initial', 'renewal', 'plan_change', 'refund')",
            name="check_payment_transaction_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'cancelled', 'refunded')",
            name="check_payment_transaction_status",
        ),
        CheckConstraint(
            "reminder_count >= 0",
            name="check_payment_transaction_reminder_count",
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
