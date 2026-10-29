
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


class ViewingSession(Base):
    __tablename__ = "viewing_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    tmdb_id = Column(Integer, nullable=False)
    media_type = Column(String(10), nullable=False)

    platform_id = Column(
        UUID(as_uuid=True),
        ForeignKey("streaming_platforms.id", ondelete="SET NULL"),
        nullable=True,
    )

    player_provider = Column(String(80))
    tracking_mode = Column(String(30), nullable=False)
    status = Column(String(20), default="active", nullable=False)

    # A client-generated ID helps prevent duplicate sessions.
    client_session_key = Column(UUID(as_uuid=True), nullable=False)

    started_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_event_at = Column(DateTime(timezone=True))
    ended_at = Column(DateTime(timezone=True))

    last_position_seconds = Column(Numeric(12, 3))
    duration_seconds = Column(Numeric(12, 3))

    observed_engagement_seconds = Column(
        Integer,
        default=0,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "client_session_key",
            name="uq_profile_client_session",
        ),
        CheckConstraint(
            "tmdb_id > 0",
            name="check_viewing_tmdb_id_positive",
        ),
        CheckConstraint(
            "media_type IN ('movie', 'tv')",
            name="check_viewing_media_type",
        ),
        CheckConstraint(
            "observed_engagement_seconds >= 0",
            name="check_observed_engagement_nonnegative",
        ),
    )


class ViewingEvent(Base):
    __tablename__ = "viewing_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    viewing_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("viewing_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Unique per session, making event submissions idempotent.
    event_key = Column(UUID(as_uuid=True), nullable=False)

    event_type = Column(String(40), nullable=False)
    source = Column(String(30), nullable=False)

    client_timestamp = Column(DateTime(timezone=True))
    received_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    position_seconds = Column(Numeric(12, 3))
    duration_seconds = Column(Numeric(12, 3))
    visible = Column(Boolean)

    payload = Column(JSONB, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "viewing_session_id",
            "event_key",
            name="uq_viewing_event_idempotency",
        ),
        CheckConstraint(
            "position_seconds IS NULL OR position_seconds >= 0",
            name="check_event_position_nonnegative",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="check_event_duration_nonnegative",
        ),
    )


class WatchProgress(Base):
    __tablename__ = "watch_progress"

    profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )

    tmdb_id = Column(Integer, primary_key=True)
    media_type = Column(String(10), primary_key=True)
    season_number = Column(Integer, nullable=True)
    episode_number = Column(Integer, nullable=True)

    last_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("viewing_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    position_seconds = Column(Numeric(12, 3))
    duration_seconds = Column(Numeric(12, 3))
    progress_ratio = Column(Numeric(6, 5))

    progress_source = Column(
        String(30),
        default="unknown",
        nullable=False,
    )
    status = Column(String(20), default="in_progress", nullable=False)

    last_watched_at = Column(
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
            "tmdb_id > 0",
            name="check_progress_tmdb_id_positive",
        ),
        CheckConstraint(
            "media_type IN ('movie', 'tv')",
            name="check_progress_media_type",
        ),
        CheckConstraint(
            "position_seconds IS NULL OR position_seconds >= 0",
            name="check_progress_position_nonnegative",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="check_progress_duration_nonnegative",
        ),
        CheckConstraint(
            "progress_ratio IS NULL OR "
            "(progress_ratio >= 0 AND progress_ratio <= 1)",
            name="check_progress_ratio_range",
        ),
        CheckConstraint(
            """
            (season_number IS NULL AND episode_number IS NULL)
            OR
            (season_number > 0 AND episode_number > 0)
            """,
            name="ck_watch_progress_valid_episode",
        ),
        CheckConstraint(
            """
            media_type = 'tv'
            OR
            (season_number IS NULL AND episode_number IS NULL)
            """,
            name="ck_watch_progress_movie_has_no_episode",
        ),
    )
