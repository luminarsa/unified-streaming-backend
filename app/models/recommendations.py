
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class ProfileContentSignal(Base):
    __tablename__ = "profile_content_signals"

    profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )

    tmdb_id = Column(Integer, primary_key=True)
    media_type = Column(String(10), primary_key=True)
    signal_type = Column(String(40), primary_key=True)

    signal_value = Column(Numeric(8, 5), nullable=False)
    confidence = Column(Numeric(4, 3), default=0.5, nullable=False)
    evidence_count = Column(Integer, default=1, nullable=False)

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "tmdb_id > 0",
            name="check_signal_tmdb_id_positive",
        ),
        CheckConstraint(
            "media_type IN ('movie', 'tv')",
            name="check_signal_media_type",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="check_signal_confidence_range",
        ),
        CheckConstraint(
            "evidence_count >= 0",
            name="check_signal_evidence_nonnegative",
        ),
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )

    tmdb_id = Column(Integer, primary_key=True)
    media_type = Column(String(10), primary_key=True)
    algorithm_version = Column(String(40), primary_key=True)

    score = Column(Numeric(12, 8), nullable=False)
    reason_code = Column(String(60), nullable=False)

    generated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "tmdb_id > 0",
            name="check_recommendation_tmdb_id_positive",
        ),
        CheckConstraint(
            "media_type IN ('movie', 'tv')",
            name="check_recommendation_media_type",
        ),
    )
