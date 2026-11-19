
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # registration, password_reset, etc.
    purpose = Column(
        String(30),
        default="registration",
        nullable=False,
    )

    # SHA-256 hash of the six-digit verification code.
    code_hash = Column(
        String(64),
        nullable=False,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    attempts = Column(
        Integer,
        default=0,
        nullable=False,
    )

    used_at = Column(DateTime(timezone=True))

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    account = relationship(
        "Account",
        back_populates="email_verifications",
    )
