
import os
import hmac
import hashlib
import secrets

from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.identity import Account, AuthSession, Profile
from app.models.email_verification import EmailVerification

from app.utils.auth import (
    hash_password,
    hash_token,
    issue_access_token,
    now_utc,
    verify_password,
    decode_access_token,
)

from app.services.mailing_system.email_service import send_email
from app.services.mailing_system.email_templates import registration_verification_email


# -------------------------------------------------
# EMAIL VERIFICATION SETTINGS
# -------------------------------------------------

VERIFICATION_CODE_LENGTH = 6
VERIFICATION_EXPIRY_MINUTES = 10
VERIFICATION_MAX_ATTEMPTS = 5
VERIFICATION_RESEND_COOLDOWN_SECONDS = 60

VERIFICATION_PURPOSE = "registration"


# -------------------------------------------------
# VERIFICATION HELPERS
# -------------------------------------------------

def generate_verification_code() -> str:
    """Generate a cryptographically secure six-digit code."""

    return f"{secrets.randbelow(1000000):06d}"


def hash_verification_code(
    account_id: UUID,
    code: str,
    purpose: str = VERIFICATION_PURPOSE,
) -> str:
    """
    Hash a verification code using HMAC-SHA256.

    A dedicated secret is required because six-digit codes
    have a relatively small number of possible combinations.
    """

    secret = os.getenv("EMAIL_VERIFICATION_SECRET")

    if not secret:
        raise RuntimeError(
            "EMAIL_VERIFICATION_SECRET is not configured."
        )

    message = f"{account_id}:{purpose}:{code}"

    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()



def send_registration_verification_email(
    email: str,
    code: str,
) -> None:
    """Build and send the registration verification email."""

    email_content = registration_verification_email(
        verification_code=code,
        platform_name="Lumina RSA",
        expiry_minutes=VERIFICATION_EXPIRY_MINUTES,
    )

    send_email(
        recipient=email,
        subject=email_content["subject"],
        html_body=email_content["html"],
        text_body=email_content["text"],
    )


def create_registration_verification(
    db: Session,
    account: Account,
) -> str:
    """
    Create and store a new registration verification code.

    Returns the raw code only so it can be sent by email.
    """

    code = generate_verification_code()

    verification = EmailVerification(
        account_id=account.id,
        purpose=VERIFICATION_PURPOSE,
        code_hash=hash_verification_code(
            account_id=account.id,
            code=code,
        ),
        expires_at=now_utc() + timedelta(
            minutes=VERIFICATION_EXPIRY_MINUTES
        ),
        attempts=0,
    )

    db.add(verification)

    return code


# -------------------------------------------------
# ACCOUNT REGISTRATION
# -------------------------------------------------

def register_account(
    db: Session,
    email: str,
    password: str,
    phone_number: str,
    profile_name: str,
    avatar_key: str | None = None,
    is_kids_profile: bool = False,
    referral_code: str | None = None,
) -> dict:
    """
    Create a pending account and its primary profile.

    The account is NOT activated until email verification.
    """

    email = email.strip().lower()
    profile_name = profile_name.strip()

    if not profile_name:
        raise HTTPException(
            status_code=422,
            detail="Primary profile name is required.",
        )

    existing_account = db.scalar(
        select(Account).where(Account.email == email)
    )

    if existing_account:
        raise HTTPException(
            status_code=409,
            detail="Email is already registered.",
        )

    try:
        # -----------------------------------------
        # 1. Create pending account
        # -----------------------------------------

        account = Account(
            email=email,
            password_hash=hash_password(password),
            phone_number=phone_number,
            status="pending_verification",
            email_verified=False,
            email_verified_at=None,
            referral_code_used=referral_code,
        )

        db.add(account)
        db.flush()

        # -----------------------------------------
        # 2. Create primary profile
        # -----------------------------------------

        profile = Profile(
            account_id=account.id,
            name=profile_name,
            avatar_key=avatar_key,
            is_kids_profile=is_kids_profile,
        )

        db.add(profile)

        # -----------------------------------------
        # 3. Create verification record
        # -----------------------------------------

        verification_code = create_registration_verification(
            db=db,
            account=account,
        )

        # Persist account, profile and verification
        # before attempting external email delivery.

        db.commit()

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="An account with these details already exists.",
        )

    except Exception:
        db.rollback()
        raise

    # ---------------------------------------------
    # 4. Send verification email
    # ---------------------------------------------

    try:
        send_registration_verification_email(
            email=account.email,
            code=verification_code,
        )

    except Exception as exc:
        import traceback

        print("\n========== REGISTRATION EMAIL ERROR ==========")
        print("Error type:", type(exc).__name__)
        print("Error message:", str(exc))
        traceback.print_exc()
        print("==============================================\n")

        raise HTTPException(
            status_code=503,
            detail=(
                "Your account was created, but we could not "
                "send the verification email. Please request "
                "a new verification code."
            ),
        ) from exc

    return {
        "success": True,
        "message": "Registration successful. Please verify your email.",
        "email": account.email,
        "verification_required": True,
        "expires_in_minutes": VERIFICATION_EXPIRY_MINUTES,
    }


# -------------------------------------------------
# VERIFY REGISTRATION EMAIL
# -------------------------------------------------

def verify_registration_code(
    db: Session,
    email: str,
    verification_code: str,
) -> dict:
    """
    Verify the registration code and activate the account.

    Issues an ACCOUNT-LEVEL token only.
    No profile_id is included in the token.
    """

    email = email.strip().lower()
    current_time = now_utc()

    # ---------------------------------------------
    # 1. Find account
    # ---------------------------------------------

    account = db.scalar(
        select(Account).where(Account.email == email)
    )

    if account is None:
        raise HTTPException(
            status_code=404,
            detail="Account not found.",
        )

    if account.email_verified or account.status == "active":
        raise HTTPException(
            status_code=409,
            detail="This email address has already been verified.",
        )

    if account.status != "pending_verification":
        raise HTTPException(
            status_code=400,
            detail="This account cannot be verified.",
        )

    # ---------------------------------------------
    # 2. Find latest unused verification code
    # ---------------------------------------------

    verification = db.scalar(
        select(EmailVerification)
        .where(
            EmailVerification.account_id == account.id,
            EmailVerification.purpose == VERIFICATION_PURPOSE,
            EmailVerification.used_at.is_(None),
        )
        .order_by(EmailVerification.created_at.desc())
    )

    if verification is None:
        raise HTTPException(
            status_code=400,
            detail="No active verification code was found. Request a new code.",
        )

    # ---------------------------------------------
    # 3. Check expiration
    # ---------------------------------------------

    if verification.expires_at <= current_time:
        verification.used_at = current_time
        db.commit()

        raise HTTPException(
            status_code=400,
            detail="Verification code has expired. Request a new code.",
        )

    # ---------------------------------------------
    # 4. Check maximum attempts
    # ---------------------------------------------

    if verification.attempts >= VERIFICATION_MAX_ATTEMPTS:
        verification.used_at = current_time
        db.commit()

        raise HTTPException(
            status_code=429,
            detail="Maximum verification attempts exceeded. Request a new code.",
        )

    # Count this attempt before checking the code.
    verification.attempts += 1

    submitted_hash = hash_verification_code(
        account_id=account.id,
        code=verification_code,
    )

    if not hmac.compare_digest(
        submitted_hash,
        verification.code_hash,
    ):
        if verification.attempts >= VERIFICATION_MAX_ATTEMPTS:
            verification.used_at = current_time

        db.commit()

        raise HTTPException(
            status_code=400,
            detail="Invalid verification code.",
        )

    try:
        # -----------------------------------------
        # 5. Activate account
        # -----------------------------------------

        account.email_verified = True
        account.email_verified_at = current_time
        account.status = "active"

        # Mark verification code as used.
        verification.used_at = current_time

        # -----------------------------------------
        # 6. Issue account-level access token
        # -----------------------------------------

        raw_token, token_hash_value, expires_at = issue_access_token(
            account_id=account.id,
        )

        session = AuthSession(
            account_id=account.id,
            token_hash=token_hash_value,
            active_profile_id=None,
            expires_at=expires_at,
            last_seen_at=current_time,
        )

        db.add(session)
        db.commit()

        return {
            "success": True,
            "message": "Email verified successfully. Your account is now active.",
            "access_token": raw_token,
            "token_type": "bearer",
            "expires_at": expires_at.isoformat(),
            "account_id": str(account.id),
            "profile_selection_required": True,
        }

    except Exception:
        db.rollback()
        raise


# -------------------------------------------------
# RESEND REGISTRATION VERIFICATION CODE
# -------------------------------------------------

def resend_registration_code(
    db: Session,
    email: str,
) -> dict:
    """Invalidate the previous code and send a new one."""

    email = email.strip().lower()
    current_time = now_utc()

    # ---------------------------------------------
    # 1. Find pending account
    # ---------------------------------------------

    account = db.scalar(
        select(Account).where(Account.email == email)
    )

    if account is None:
        raise HTTPException(
            status_code=404,
            detail="Account not found.",
        )

    if account.email_verified or account.status == "active":
        raise HTTPException(
            status_code=409,
            detail="This account has already been verified.",
        )

    if account.status != "pending_verification":
        raise HTTPException(
            status_code=400,
            detail="This account cannot request verification.",
        )

    # ---------------------------------------------
    # 2. Find previous unused code
    # ---------------------------------------------

    previous_verification = db.scalar(
        select(EmailVerification)
        .where(
            EmailVerification.account_id == account.id,
            EmailVerification.purpose == VERIFICATION_PURPOSE,
            EmailVerification.used_at.is_(None),
        )
        .order_by(EmailVerification.created_at.desc())
    )

    # ---------------------------------------------
    # 3. Enforce resend cooldown
    # ---------------------------------------------

    if previous_verification is not None:
        cooldown_end = (
            previous_verification.created_at
            + timedelta(seconds=VERIFICATION_RESEND_COOLDOWN_SECONDS)
        )

        if current_time < cooldown_end:
            remaining_seconds = int(
                (cooldown_end - current_time).total_seconds()
            )

            raise HTTPException(
                status_code=429,
                detail=f"Please wait {remaining_seconds} seconds before requesting another code.",
            )

    try:
        # -----------------------------------------
        # 4. Invalidate previous code
        # -----------------------------------------

        if previous_verification is not None:
            previous_verification.used_at = current_time

        # -----------------------------------------
        # 5. Create replacement code
        # -----------------------------------------

        new_code = create_registration_verification(
            db=db,
            account=account,
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    # ---------------------------------------------
    # 6. Send replacement email
    # ---------------------------------------------

    try:
        send_registration_verification_email(
            email=account.email,
            code=new_code,
        )

    except Exception as exc:
        import traceback

        print("\n========== RESEND EMAIL ERROR ==========")
        print("Error type:", type(exc).__name__)
        print("Error message:", str(exc))
        traceback.print_exc()
        print("========================================\n")

        raise HTTPException(
            status_code=503,
            detail="Could not send the verification email. Please try again later.",
        ) from exc

    return {
        "success": True,
        "message": "A new verification code has been sent to your email.",
        "expires_in_minutes": VERIFICATION_EXPIRY_MINUTES,
    }


# -------------------------------------------------
# LOGIN
# -------------------------------------------------

def login_account(
    db: Session,
    email: str,
    password: str,
) -> dict:

    email = email.strip().lower()

    account = db.scalar(
        select(Account).where(Account.email == email)
    )

    if (
        account is None
        or account.status != "active"
        or not account.email_verified
        or not verify_password(password, account.password_hash)
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        )

    try:
        raw_token, token_hash_value, expires_at = issue_access_token(
            account_id=account.id,
        )

        session = AuthSession(
            account_id=account.id,
            token_hash=token_hash_value,
            active_profile_id=None,
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


# -------------------------------------------------
# PROFILE SELECTION
# -------------------------------------------------

def select_profile(
    db: Session,
    raw_token: str,
    profile_id,
) -> dict:

    token_data = decode_access_token(
        db=db,
        raw_token=raw_token,
    )

    account_id = token_data["account_id"]

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
        old_session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == hash_token(raw_token)
            )
        )

        if old_session is None or old_session.revoked_at is not None:
            raise HTTPException(
                status_code=401,
                detail="Your session is no longer valid.",
            )

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
