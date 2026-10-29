
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.telemetry import (
    ViewingSession,
    ViewingEvent,
    WatchProgress,
)
from app.schemas.telemetry import (
    ViewingSessionCreate,
    ViewingEventCreate,
)


def create_or_get_session(
    db: Session,
    profile_id: UUID,
    data: ViewingSessionCreate,
) -> ViewingSession:
    existing = db.scalar(
        select(ViewingSession).where(
            ViewingSession.profile_id == profile_id,
            ViewingSession.client_session_key
            == data.client_session_key,
        )
    )

    if existing:
        if (
            existing.tmdb_id != data.tmdb_id
            or existing.media_type != data.media_type
        ):
            raise HTTPException(
                status_code=409,
                detail="Session key is already used for another title.",
            )
        return existing

    viewing_session = ViewingSession(
        profile_id=profile_id,
        tmdb_id=data.tmdb_id,
        media_type=data.media_type,
        platform_id=data.platform_id,
        player_provider=data.player_provider,
        tracking_mode=data.tracking_mode,
        client_session_key=data.client_session_key,
        status="active",
    )

    db.add(viewing_session)

    try:
        db.commit()
        db.refresh(viewing_session)
    except Exception:
        db.rollback()
        # Another request may have created the same session
        # concurrently. Re-check before returning an error.
        existing = db.scalar(
            select(ViewingSession).where(
                ViewingSession.profile_id == profile_id,
                ViewingSession.client_session_key
                == data.client_session_key,
            )
        )
        if existing:
            if (
                existing.tmdb_id != data.tmdb_id
                or existing.media_type != data.media_type
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Session key is already used for another title.",
                )
            return existing
        raise

    return viewing_session


def record_viewing_event(
    db: Session,
    profile_id: UUID,
    viewing_session_id: UUID,
    data: ViewingEventCreate,
) -> dict:
    viewing_session = db.scalar(
        select(ViewingSession).where(
            ViewingSession.id == viewing_session_id,
            ViewingSession.profile_id == profile_id,
        )
    )

    if viewing_session is None:
        raise HTTPException(
            status_code=404,
            detail="Viewing session not found.",
        )

    if viewing_session.status == "ended":
        raise HTTPException(
            status_code=409,
            detail="This viewing session has already ended.",
        )

    if viewing_session.media_type == "tv":
        if data.season_number is None or data.episode_number is None:
            raise HTTPException(
                status_code=422,
                detail="TV events require season_number and episode_number.",
            )
    elif (
        data.season_number is not None
        or data.episode_number is not None
    ):
        raise HTTPException(
            status_code=422,
            detail="Movie events cannot contain episode numbers.",
        )

    now = datetime.now(timezone.utc)

    event_values = {
        "id": UUID(int=0),  # Replaced below with a generated UUID.
        "viewing_session_id": viewing_session.id,
        "event_key": data.event_key,
        "event_type": data.event_type,
        "source": "vidrock",
        "client_timestamp": data.client_timestamp,
        "position_seconds": data.position_seconds,
        "duration_seconds": data.duration_seconds,
        "visible": data.visible,
        "payload": data.payload,
    }
    # Let PostgreSQL generate a UUID for the event row.
    event_values.pop("id")

    event_statement = (
        insert(ViewingEvent)
        .values(**event_values)
        .on_conflict_do_nothing(
            constraint="uq_viewing_event_idempotency"
        )
        .returning(ViewingEvent.id)
    )

    inserted_event_id = db.execute(
        event_statement
    ).scalar_one_or_none()

    if inserted_event_id is None:
        # Duplicate event: don't apply progress a second time.
        db.rollback()
        return {"accepted": True, "duplicate": True}

    position = data.position_seconds
    duration = data.duration_seconds

    if position is not None:
        viewing_session.last_position_seconds = Decimal(str(position))

    if duration is not None:
        viewing_session.duration_seconds = Decimal(str(duration))

    viewing_session.last_event_at = now

    if data.event_type == "ended":
        viewing_session.status = "ended"
        viewing_session.ended_at = now

    # Do not let malformed or delayed events overwrite newer progress.
    should_update_progress = (
        data.event_type in {"play", "pause", "seeked", "timeupdate", "ended"}
        and position is not None
    )

    if should_update_progress:
        ratio = None
        if duration is not None and duration > 0:
            ratio = min(max(position / duration, 0), 1)

        progress_status = (
            "completed"
            if data.event_type == "ended"
            or (ratio is not None and ratio >= 0.90)
            else "in_progress"
        )

        progress_values = {
            "profile_id": profile_id,
            "tmdb_id": viewing_session.tmdb_id,
            "media_type": viewing_session.media_type,
            "season_number": data.season_number,
            "episode_number": data.episode_number,
            "last_session_id": viewing_session.id,
            "position_seconds": Decimal(str(position)),
            "duration_seconds": (
                Decimal(str(duration)) if duration is not None else None
            ),
            "progress_ratio": (
                Decimal(str(round(ratio, 5)))
                if ratio is not None
                else None
            ),
            "progress_source": "vidrock",
            "status": progress_status,
            "last_watched_at": now,
            "updated_at": now,
        }

        progress_statement = insert(WatchProgress).values(
            **progress_values
        )

        # The composite primary key identifies one latest resume
        # record per profile and title.
        progress_statement = progress_statement.on_conflict_do_update(
            index_elements=[
                WatchProgress.profile_id,
                WatchProgress.tmdb_id,
                WatchProgress.media_type,
            ],
            set_={
                "season_number": progress_statement.excluded.season_number,
                "episode_number": progress_statement.excluded.episode_number,
                "last_session_id": progress_statement.excluded.last_session_id,
                "position_seconds": progress_statement.excluded.position_seconds,
                "duration_seconds": progress_statement.excluded.duration_seconds,
                "progress_ratio": progress_statement.excluded.progress_ratio,
                "progress_source": progress_statement.excluded.progress_source,
                "status": progress_statement.excluded.status,
                "last_watched_at": progress_statement.excluded.last_watched_at,
                "updated_at": progress_statement.excluded.updated_at,
            },
        )

        db.execute(progress_statement)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"accepted": True, "duplicate": False}


def get_profile_progress(
    db: Session,
    profile_id: UUID,
    limit: int = 20,
) -> list[WatchProgress]:
    statement = (
        select(WatchProgress)
        .where(
            WatchProgress.profile_id == profile_id,
            WatchProgress.status == "in_progress",
        )
        .order_by(WatchProgress.last_watched_at.desc())
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def get_title_progress(
    db: Session,
    profile_id: UUID,
    tmdb_id: int,
    media_type: str,
) -> WatchProgress | None:
    return db.scalar(
        select(WatchProgress).where(
            WatchProgress.profile_id == profile_id,
            WatchProgress.tmdb_id == tmdb_id,
            WatchProgress.media_type == media_type,
        )
    )
