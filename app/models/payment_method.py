
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Payment provider, e.g. PayPal
    provider = Column(
        String(50),
        nullable=False,
        default="paypal",
    )

    # PayPal customer reference
    provider_customer_id = Column(String(200))

    # Encrypted PayPal vault token.
    # Never store raw card numbers or CVV.
    encrypted_payment_token = Column(Text, nullable=False)

    # SHA-256 fingerprint used to detect duplicate saved tokens
    token_fingerprint = Column(String(64), nullable=False)

    # Safe card information for display
    card_brand = Column(String(40))
    last_four = Column(String(4))

    expiry_month = Column(Integer)
    expiry_year = Column(Integer)

    status = Column(
        String(30),
        nullable=False,
        default="active",
    )

    is_default = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "provider",
            "token_fingerprint",
            name="uq_payment_method_account_provider_fingerprint",
        ),
        CheckConstraint(
            "last_four IS NULL OR length(last_four) = 4",
            name="check_payment_method_last_four",
        ),
        CheckConstraint(
            "expiry_month IS NULL OR (expiry_month >= 1 AND expiry_month <= 12)",
            name="check_payment_method_expiry_month",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'deleted')",
            name="check_payment_method_status",
        ),
    )
