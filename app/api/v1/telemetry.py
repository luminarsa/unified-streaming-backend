
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.identity import Profile
from app.models.telemetry import WatchProgress
from app.schemas.telemetry import (
    WatchListCreate,
    WatchListItemResponse,
    WatchListPlatformGroup,
    WatchListCheckResponse,
    WatchListDeleteResponse,
    ViewingSessionCreate,
    ViewingSessionResponse,
    ViewingEventCreate,
    WatchProgressResponse,
)
from app.services.telemetry import (
    add_to_watchlist,
    get_all_watchlists,
    get_platform_watchlist,
    check_watchlist_item,
    delete_watchlist_item,
    create_or_get_session,
    record_viewing_event,
    get_profile_progress,
    get_title_progress,
)

from app.api.v1.dependencies import get_active_profile
# IMPORTANT:
# Replace this import with the module containing your existing function.
from app.utils.auth import decode_access_token


router = APIRouter(prefix="/telemetry", tags=["Telemetry"])
bearer_scheme = HTTPBearer()


@router.post(
    "",
    response_model=WatchListItemResponse,
    status_code=201,
)
async def create_watchlist_item(
    data: WatchListCreate,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    """Add a movie or TV show to the selected platform watchlist."""

    return await add_to_watchlist(
        db=db,
        profile_id=profile.id,
        data=data,
    )


@router.get(
    "",
    response_model=list[WatchListPlatformGroup],
)
def list_all_watchlists(
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    """Get all watchlists for the active profile, grouped by platform."""

    return get_all_watchlists(
        db=db,
        profile_id=profile.id,
    )


@router.get(
    "/check",
    response_model=WatchListCheckResponse,
)
def check_if_saved(
    platform_id: UUID,
    tmdb_id: int = Query(gt=0),
    media_type: str = Query(pattern="^(movie|tv)$"),
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    """Check whether a title exists in the selected platform watchlist."""

    item = check_watchlist_item(
        db=db,
        profile_id=profile.id,
        platform_id=platform_id,
        tmdb_id=tmdb_id,
        media_type=media_type,
    )

    return {
        "saved": item is not None,
        "item_id": item.id if item else None,
    }


@router.get(
    "/{platform_id}",
    response_model=list[WatchListItemResponse],
)
def list_platform_watchlist(
    platform_id: UUID,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    """Get the active profile's watchlist for one platform."""

    return get_platform_watchlist(
        db=db,
        profile_id=profile.id,
        platform_id=platform_id,
    )


@router.delete(
    "/{item_id}",
    response_model=WatchListDeleteResponse,
)
def remove_watchlist_item(
    item_id: UUID,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    """Remove an item from the active profile's watchlist."""

    delete_watchlist_item(
        db=db,
        profile_id=profile.id,
        item_id=item_id,
    )

    return {
        "message": "Watchlist item removed successfully.",
        "item_id": item_id,
    }


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
