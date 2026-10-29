
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.identity import Profile
from app.models.telemetry import WatchProgress
from app.schemas.telemetry import (
    ViewingSessionCreate,
    ViewingSessionResponse,
    ViewingEventCreate,
    WatchProgressResponse,
)
from app.services.telemetry import (
    create_or_get_session,
    record_viewing_event,
    get_profile_progress,
    get_title_progress,
)

# IMPORTANT:
# Replace this import with the module containing your existing function.
from app.utils.auth import decode_access_token


router = APIRouter(prefix="/telemetry", tags=["Telemetry"])
bearer_scheme = HTTPBearer()


def get_active_profile(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Profile:
    token_data = decode_access_token(
        db=db,
        raw_token=credentials.credentials,
    )

    account_id = token_data["account_id"]
    profile_id = token_data.get("profile_id")

    if not profile_id:
        raise HTTPException(
            status_code=403,
            detail="Select a profile before accessing telemetry.",
        )

    profile = db.get(Profile, profile_id)

    if profile is None or str(profile.account_id) != str(account_id):
        raise HTTPException(
            status_code=403,
            detail="The active profile does not belong to this account.",
        )

    return profile


@router.post(
    "/sessions",
    response_model=ViewingSessionResponse,
)
def start_viewing_session(
    data: ViewingSessionCreate,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    return create_or_get_session(
        db=db,
        profile_id=profile.id,
        data=data,
    )


@router.post("/sessions/{session_id}/events")
def submit_viewing_event(
    session_id: UUID,
    data: ViewingEventCreate,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    return record_viewing_event(
        db=db,
        profile_id=profile.id,
        viewing_session_id=session_id,
        data=data,
    )


@router.get(
    "/progress",
    response_model=list[WatchProgressResponse],
)
def list_watch_progress(
    limit: int = Query(default=20, ge=1, le=100),
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    return get_profile_progress(
        db=db,
        profile_id=profile.id,
        limit=limit,
    )


@router.get(
    "/progress/{media_type}/{tmdb_id}",
    response_model=WatchProgressResponse,
)
def read_title_progress(
    media_type: str,
    tmdb_id: int,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    if media_type not in {"movie", "tv"}:
        raise HTTPException(
            status_code=422,
            detail="media_type must be 'movie' or 'tv'.",
        )

    if tmdb_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="tmdb_id must be greater than zero.",
        )

    progress = get_title_progress(
        db=db,
        profile_id=profile.id,
        tmdb_id=tmdb_id,
        media_type=media_type,
    )

    if progress is None:
        raise HTTPException(
            status_code=404,
            detail="No watch progress found for this title.",
        )

    return progress
