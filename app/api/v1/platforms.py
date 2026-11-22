from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.v1.dependencies import bearer_scheme
from app.models.identity import Profile
from app.services.auth import decode_access_token

from app.services.platform_catalog import (
    get_platform_movies,
    get_platform_shows,
    get_platform_originals,
    get_platform_channels
)


router = APIRouter(
    prefix="/platforms",
    tags=["Platform Catalog"],
)


def get_authenticated_profile(
    credentials: HTTPAuthorizationCredentials,
    db: Session,
) -> Profile:

    token_data = decode_access_token(
        db=db,
        raw_token=credentials.credentials,
    )

    try:
        account_id = UUID(str(token_data["account_id"]))
        active_profile_id = UUID(str(token_data["profile_id"]))

    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=403,
            detail="Select a valid profile before accessing platform content.",
        )

    profile = db.get(Profile, active_profile_id)

    if profile is None or profile.account_id != account_id:
        raise HTTPException(
            status_code=403,
            detail="The active profile does not belong to this account.",
        )

    return profile


@router.get("/{platform_id}/movies")
def get_platform_movies_endpoint(
    platform_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    profile = get_authenticated_profile(
        credentials=credentials,
        db=db,
    )

    return get_platform_movies(
        db=db,
        platform_id=platform_id,
        profile=profile,
    )


@router.get("/{platform_id}/shows")
def get_platform_shows_endpoint(
    platform_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    profile = get_authenticated_profile(
        credentials=credentials,
        db=db,
    )

    return get_platform_shows(
        db=db,
        platform_id=platform_id,
        profile=profile,
    )


@router.get("/{platform_id}/originals")
def get_platform_originals_endpoint(
    platform_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    profile = get_authenticated_profile(
        credentials=credentials,
        db=db,
    )

    return get_platform_originals(
        db=db,
        platform_id=platform_id,
        profile=profile,
    )

@router.get("/{platform_id}/channels")
def get_platform_channels_endpoint(
    platform_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    profile = get_authenticated_profile(
        credentials=credentials,
        db=db,
    )

    return get_platform_channels(
        db=db,
        platform_id=platform_id,
        profile=profile,
    )