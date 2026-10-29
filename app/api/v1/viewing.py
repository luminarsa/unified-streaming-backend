from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.v1.dependencies import get_demo_account_id
from app.models.identity import Profile
from app.models.commercial import StreamingPlatform
from app.models.telemetry import ViewingSession, ViewingEvent
from app.schemas.telemetry import ViewingSessionCreate, ViewingSessionResponse, ViewingEventCreate, ViewingEventAck
from app.services.entitlements import EntitlementService

router = APIRouter()
entitlements = EntitlementService()

@router.post("/viewing-sessions", response_model=ViewingSessionResponse, status_code=201)
def create_viewing_session(payload: ViewingSessionCreate,
                           account_id: UUID = Depends(get_demo_account_id),
                           db: Session = Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.id == payload.profile_id, Profile.account_id == account_id))
    if not profile:
        raise HTTPException(status_code=404, detail={"code": "PROFILE_NOT_FOUND"})
    decision = entitlements.check(db, account_id, payload.profile_id, payload.platform_slug)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail={"code": decision.reason_code})
    platform = db.scalar(select(StreamingPlatform).where(StreamingPlatform.slug == payload.platform_slug))
    existing = db.scalar(select(ViewingSession).where(
        ViewingSession.profile_id == payload.profile_id,
        ViewingSession.client_session_key == payload.client_session_key))
    if existing:
        return ViewingSessionResponse(session_id=existing.id, status=existing.status, tracking_mode=existing.tracking_mode)
    session = ViewingSession(profile_id=payload.profile_id, tmdb_id=payload.tmdb_id,
        media_type=payload.media_type, platform_id=platform.id if platform else None,
        player_provider=payload.player_provider, tracking_mode="observed_only",
        client_session_key=payload.client_session_key)
    db.add(session)
    db.commit()
    db.refresh(session)
    return ViewingSessionResponse(session_id=session.id, status=session.status, tracking_mode=session.tracking_mode)

@router.post("/viewing-sessions/{session_id}/events", response_model=ViewingEventAck)
def ingest_event(session_id: UUID, payload: ViewingEventCreate,
                 account_id: UUID = Depends(get_demo_account_id),
                 db: Session = Depends(get_db)):
    session = db.scalar(select(ViewingSession).join(Profile, Profile.id == ViewingSession.profile_id).where(
        ViewingSession.id == session_id, Profile.account_id == account_id))
    if not session:
        raise HTTPException(status_code=404, detail={"code": "VIEWING_SESSION_NOT_FOUND"})
    existing = db.scalar(select(ViewingEvent).where(
        ViewingEvent.viewing_session_id == session_id, ViewingEvent.event_key == payload.event_key))
    if existing:
        return ViewingEventAck(accepted=True, duplicate=True, event_id=existing.id)
    # Observed-only sessions cannot persist a claimed media position.
    position = payload.position_seconds if session.tracking_mode in {"player_events", "player_position"} and payload.source == "player" else None
    duration = payload.duration_seconds if position is not None else None
    event = ViewingEvent(viewing_session_id=session_id, event_key=payload.event_key,
        event_type=payload.event_type, source=payload.source, client_timestamp=payload.client_timestamp,
        position_seconds=position, duration_seconds=duration, visible=payload.visible,
        payload={"player_state": payload.player_state} if payload.player_state else {})
    db.add(event)
    db.commit()
    db.refresh(event)
    return ViewingEventAck(accepted=True, duplicate=False, event_id=event.id)
