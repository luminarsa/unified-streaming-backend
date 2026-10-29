from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.identity import AuthSession
from app.utils.auth import verify_token_validity


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

    return verify_token_validity(
        db=db,
        raw_token=credentials.credentials,
    )


def get_current_account_id(
    current_session: AuthSession = Depends(get_current_session),
):
    """Return the account ID associated with the valid session."""

    return current_session.account_id
