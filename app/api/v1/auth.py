
from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db

from app.schemas.auth import (
    RegisterRequest,
    VerifyRegistrationRequest,
    ResendVerificationRequest,
    RegistrationResponse,
    RegistrationVerificationResponse,
    ResendVerificationResponse,
    LoginRequest,
    SelectProfileRequest,
)

from app.services.auth import (
    register_account,
    verify_registration_code,
    resend_registration_code,
    login_account,
    select_profile,
)


bearer_scheme = HTTPBearer()

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


# =================================================
# REGISTER ACCOUNT
# =================================================

@router.post(
    "/register",
    status_code=201,
    response_model=RegistrationResponse,
)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db),
):
    return register_account(
        db=db,
        email=request.email,
        password=request.password,
        phone_number=request.phone_number,
        profile_name=request.primary_profile.name,
        avatar_key=request.primary_profile.avatar_url,
        is_kids_profile=request.primary_profile.is_kids_profile,
        referral_code=request.referral_code,
    )


# =================================================
# VERIFY REGISTRATION EMAIL
# =================================================

@router.post(
    "/verify-registration",
    status_code=200,
    response_model=RegistrationVerificationResponse,
)
def verify_registration(
    request: VerifyRegistrationRequest,
    db: Session = Depends(get_db),
):
    return verify_registration_code(
        db=db,
        email=request.email,
        verification_code=request.verification_code,
    )


# =================================================
# RESEND VERIFICATION EMAIL
# =================================================

@router.post(
    "/resend-verification",
    status_code=200,
    response_model=ResendVerificationResponse,
)
def resend_verification(
    request: ResendVerificationRequest,
    db: Session = Depends(get_db),
):
    return resend_registration_code(
        db=db,
        email=request.email,
    )


# =================================================
# LOGIN
# =================================================

@router.post("/login")
def login(
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    return login_account(
        db=db,
        email=request.email,
        password=request.password,
    )


# =================================================
# SELECT PROFILE
# =================================================

@router.post("/select-profile")
def select_profile_endpoint(
    request: SelectProfileRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    return select_profile(
        db=db,
        raw_token=credentials.credentials,
        profile_id=request.profile_id,
    )
