
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
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
    code = Column(String(40), nullable=False, unique=True)
    name = Column(String(80), nullable=False)

    # Store prices in cents: R100.00 = 10000
    price_minor = Column(Numeric, nullable=False)
    currency = Column(String(3), default="ZAR", nullable=False)
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

    status = Column(String(30), default="pending", nullable=False)

    provider = Column(String(50))
    provider_customer_id = Column(String(200))
    provider_subscription_id = Column(String(200))

    current_period_start = Column(DateTime(timezone=True))
    current_period_end = Column(DateTime(timezone=True))

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
