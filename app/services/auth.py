from datetime import timedelta
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.commercial import Plan, Subscription
from app.models.identity import Account, AuthSession, Profile
from app.utils.auth import (
    SESSION_DAYS,
    hash_password,
    hash_token,
    issue_access_token,
    now_utc,
    verify_password,
    decode_access_token,
)

def register_account(
    db: Session,
    email: str,
    password: str,
    profile_name: str,
    avatar_key: str | None = None,
) -> dict:
    """Create an account and its primary viewer profile."""

    email = email.strip().lower()
    profile_name = profile_name.strip()

    existing_account = db.scalar(
        select(Account).where(Account.email == email)
    )

    if existing_account:
        raise HTTPException(
            status_code=409,
            detail="Email is already registered.",
        )

    if not profile_name:
        raise HTTPException(
            status_code=422,
            detail="Primary profile name is required.",
        )

    try:
        account = Account(
            email=email,
            password_hash=hash_password(password),
            status="active",
        )

        db.add(account)
        db.flush()

        profile = Profile(
            account_id=account.id,
            name=profile_name,
            avatar_key=avatar_key,
            is_kids_profile=False,
        )

        db.add(profile)
        db.commit()

        db.refresh(account)
        db.refresh(profile)

        return {
            "message": "Account created successfully.",
            "account": account,
            "primary_profile": profile,
        }

    except Exception:
        db.rollback()
        raise


def login_account(db: Session, email: str, password: str):
    email = email.strip().lower()

    account = db.scalar(
        select(Account).where(Account.email == email)
    )

    if (
        account is None
        or account.status != "active"
        or not verify_password(password, account.password_hash)
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        )

    try:
        # Issue a token containing the account ID only.
        raw_token, token_hash, expires_at = issue_access_token(
            account_id=account.id,
        )

        session = AuthSession(
            account_id=account.id,
            token_hash=token_hash,
            expires_at=expires_at,
            last_seen_at=now_utc(),
        )

        db.add(session)
        db.commit()

        return {
            "access_token": raw_token,
            "token_type": "bearer",
            "expires_at": expires_at.isoformat(),
        }

    except Exception:
        db.rollback()
        raise

def select_profile(
    db: Session,
    raw_token: str,
    profile_id,
):
    # Decode the account-level token.
    token_data = decode_access_token(
        db=db,
        raw_token=raw_token,
    )

    account_id = token_data["account_id"]

    # Confirm that this profile belongs to the signed-in account.
    profile = db.scalar(
        select(Profile).where(
            Profile.id == profile_id,
            Profile.account_id == account_id,
        )
    )

    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="Profile not found for this account.",
        )

    try:
        # Find the current session so we can rotate the token.
        old_session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == hash_token(raw_token)
            )
        )

        # Issue a new token containing both IDs.
        new_token, new_token_hash, expires_at = issue_access_token(
            account_id=account_id,
            profile_id=profile.id,
        )

        new_session = AuthSession(
            account_id=account_id,
            token_hash=new_token_hash,
            active_profile_id=profile.id,
            expires_at=expires_at,
            last_seen_at=now_utc(),
        )

        # Invalidate the old account-only token.
        old_session.revoked_at = now_utc()
        old_session.revoked_reason = "profile_selected"

        db.add(new_session)
        db.commit()

        return {
            "access_token": new_token,
            "token_type": "bearer",
            "expires_at": expires_at.isoformat(),
            "account_id": str(account_id),
            "profile_id": str(profile.id),
        }

    except Exception:
        db.rollback()
        raise