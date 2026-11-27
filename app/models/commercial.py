
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class Plan(Base):
    __tablename__ = "plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category = Column(String) #Students, House Hold, Commercial & Short Term Rentals
    code = Column(String(40), nullable=False, unique=True)
    name = Column(String(80), nullable=False)

    # Store prices in cents: R100.00 = 10000
    price_minor = Column(Numeric, nullable=False)
    currency = Column(String(3), default="ZAR", nullable=False)
    paypal_price = Column(Numeric(10, 2))
    paypal_currency = Column(String(3))
    # Card2Crypto checkout configuration
    card2crypto_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    card2crypto_minimum_usd = Column(
        Numeric(12, 2),
        nullable=False,
        default=2.00,
        server_default="2.00",
    )
    billing_interval = Column(String(20), default="Monthly", nullable=False)
    max_simultaneous_streams = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "price_minor >= 0",
            name="check_plan_price_nonnegative",
        ),
        CheckConstraint(
            "currency = 'ZAR'",
            name="check_plan_currency_zar",
        ),
    )


class Card2CryptoPayment(Base):
    __tablename__ = "card2crypto_payments"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Lumina payment transaction.
    payment_transaction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("payment_transactions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Unique reference sent to Card2Crypto.
    payment_reference = Column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    # Card2Crypto receiving wallet information.
    encrypted_address_in = Column(Text, nullable=False)
    polygon_address_in = Column(String(100), nullable=False)

    # Encrypted provider IPN token.
    encrypted_ipn_token = Column(Text, nullable=False)

    # Authentication for the callback URL.
    callback_token_hash = Column(String(64), nullable=False)

    # Original ZAR price and USD conversion.
    zar_amount = Column(Numeric(12, 2), nullable=False)
    usd_amount = Column(Numeric(12, 2), nullable=False)
    exchange_rate = Column(Numeric(18, 8), nullable=False)

    # Hosted checkout URL.
    checkout_url = Column(Text, nullable=False)

    # Provider payment information.
    coin = Column(String(50))
    value_coin = Column(Numeric(18, 8))
    value_forwarded_coin = Column(Numeric(18, 8))

    txid_in = Column(String(100))
    txid_out = Column(String(100))

    # Card2Crypto payment status.
    status = Column(
        String(30),
        nullable=False,
        default="pending",
        server_default="pending",
    )

    # Callback and reconciliation timestamps.
    callback_received_at = Column(DateTime(timezone=True))
    paid_at = Column(DateTime(timezone=True))
    last_status_check_at = Column(DateTime(timezone=True))

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
        CheckConstraint(
            "zar_amount > 0",
            name="check_card2crypto_zar_amount",
        ),
        CheckConstraint(
            "usd_amount > 0",
            name="check_card2crypto_usd_amount",
        ),
        CheckConstraint(
            "exchange_rate > 0",
            name="check_card2crypto_exchange_rate",
        ),
        CheckConstraint(
            "status IN ('pending', 'paid', 'failed', 'expired')",
            name="check_card2crypto_status",
        ),
    )


class PlanFeature(Base):
    __tablename__ = "plan_features"

    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), primary_key=True)
    feature_code = Column(String(60), primary_key=True)
    is_enabled = Column(Boolean, nullable=False, default=True)

class PlanEntitlement(Base):
    __tablename__ = "plan_entitlements"

    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), primary_key=True)
    platform_id = Column(UUID(as_uuid=True), ForeignKey("streaming_platforms.id", ondelete="RESTRICT"), primary_key=True)



class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    plan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("plans.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # A subscription starts pending and is activated only
    # after Lumina verifies successful payment.
    status = Column(String(30), default="pending", nullable=False)

    provider = Column(String(50))
    provider_customer_id = Column(String(200))
    provider_subscription_id = Column(String(200))

    current_period_start = Column(DateTime(timezone=True))
    current_period_end = Column(DateTime(timezone=True))

    # Next date on which Lumina should generate a renewal invoice.
    next_billing_at = Column(DateTime(timezone=True))

    # Optional grace period after an unpaid renewal.
    grace_period_ends_at = Column(DateTime(timezone=True))

    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    cancelled_at = Column(DateTime(timezone=True))

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