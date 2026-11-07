from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.identity import AuthSession, Profile
from app.utils.auth import decode_access_token


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
    db: Session = Depends(get_db),
) -> AuthSession:
    """Return the authenticated session for a protected API request."""

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTHENTICATION_REQUIRED"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return decode_access_token(
        db=db,
        raw_token=credentials.credentials,
    )


def get_current_account_id(
    current_session: AuthSession = Depends(get_current_session),
):
    """Return the account ID associated with the valid session."""

    return current_session.account_id

def get_active_profile(
    current_session: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Profile:
    """Return the profile selected in the authenticated session."""

    profile_id = current_session.active_profile_id

    if not profile_id:
        raise HTTPException(
            status_code=403,
            detail="Select a profile before accessing this resource.",
        )

    profile = db.get(Profile, profile_id)

    if profile is None or str(profile.account_id) != str(current_session.account_id):
        raise HTTPException(
            status_code=403,
            detail="The active profile does not belong to this account.",
        )

    return profile