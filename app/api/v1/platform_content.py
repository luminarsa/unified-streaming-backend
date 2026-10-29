from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.identity import Profile
from app.services.content import get_unified_home, get_platform_home
from app.utils.auth import decode_access_token


router = APIRouter(
    prefix="/platforms",
    tags=["Platform Content"],
)

bearer_scheme = HTTPBearer()


@router.get("/lumina-home", include_in_schema=True)
def get_unified_account_home(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    # 1. Authenticate the account.
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
        )

    token_data = decode_access_token(
        db=db,
        raw_token=credentials.credentials,
    )

    account_id = token_data["account_id"]
    active_profile_id = token_data.get("profile_id")

    # 2. Require an active profile.
    if not active_profile_id:
        raise HTTPException(
            status_code=403,
            detail="Select a profile before accessing the home page.",
        )

    try:
        profile_id = UUID(str(active_profile_id))
        account_uuid = UUID(str(account_id))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=401,
            detail="Invalid account or profile identity in access token.",
        )

    profile = db.get(Profile, profile_id)

    if profile is None or profile.account_id != account_uuid:
        raise HTTPException(
            status_code=403,
            detail="The active profile does not belong to this account.",
        )

    # 3. Return the unified home page.
    return get_unified_home(
        db=db,
        account_id=account_uuid,
        profile=profile,
    )

@router.get("/{platform_id}/home")
def get_platform_home_page(
    platform_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    token_data = decode_access_token(
        db=db,
        raw_token=credentials.credentials,
    )

    account_id = token_data["account_id"]
    active_profile_id = token_data.get("profile_id")

    if not active_profile_id:
        raise HTTPException(
            status_code=403,
            detail="Select a profile before accessing platform content.",
        )

    profile = db.get(Profile, active_profile_id)

    if profile is None or str(profile.account_id) != str(account_id):
        raise HTTPException(
            status_code=403,
            detail="The active profile does not belong to this account.",
        )

    return get_platform_home(
        db=db,
        platform_id=platform_id,
        profile=profile,
    )