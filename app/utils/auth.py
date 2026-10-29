import os
import hashlib
import hmac
import secrets
import jwt
from uuid import UUID
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import Account, AuthSession

load_dotenv()

SESSION_DAYS = 30
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)

    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
    )

    return (
        f"scrypt$16384$8$1$"
        f"{salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$", 5)

        if algorithm != "scrypt":
            return False

        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
        )

        return hmac.compare_digest(actual.hex(), expected_hex)

    except (ValueError, TypeError):
        return False


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()


def issue_access_token(
    account_id: UUID,
    profile_id: UUID | None = None,
) -> tuple[str, str, datetime]:
    issued_at = now_utc()
    expires_at = issued_at + timedelta(days=SESSION_DAYS)

    payload = {
        "account_id": str(account_id),
        "iat": issued_at,
        "exp": expires_at,
        "jti": secrets.token_urlsafe(16),
    }

    # Only include profile_id after a profile has been selected.
    if profile_id is not None:
        payload["profile_id"] = str(profile_id)

    access_token = jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    return access_token, hash_token(access_token), expires_at


def decode_access_token(db: Session, raw_token: str) -> dict:
    if not raw_token:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_TOKEN"},
        )

    # 1. Validate the JWT signature and claims.
    try:
        payload = jwt.decode(
            raw_token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

        account_id = str(payload["account_id"])

        profile_id = (
            str(payload["profile_id"])
            if payload.get("profile_id")
            else None
        )

    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=401,
            detail={"code": "JWT_DECODE_FAILED"},
        )

    # 6. Check account status.
    account = db.scalar(
        select(Account).where(Account.id == account_id)
    )

    if account is None or account.status != "active":
        raise HTTPException(
            status_code=401,
            detail={"code": "ACCOUNT_INACTIVE"},
        )

    return {
        "account_id": account_id,
        "profile_id": profile_id,
    }