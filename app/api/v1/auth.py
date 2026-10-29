
from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, SelectProfileRequest
from app.services.auth import register_account, login_account, select_profile

bearer_scheme = HTTPBearer()

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

@router.post("/register", status_code=201)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db),
):
    result = register_account(
        db=db,
        email=str(request.email),
        password=request.password,
        profile_name=request.primary_profile.name,
        avatar_key=request.primary_profile.avatar_key,
    )

    return {
        "message": result["message"],
        "account": {
            "id": str(result["account"].id),
            "email": result["account"].email,
            "status": result["account"].status,
        },
        "primary_profile": {
            "id": str(result["primary_profile"].id),
            "name": result["primary_profile"].name,
            "avatar_key": result["primary_profile"].avatar_key,
        },
    }


@router.post("/login")
def login(
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    return login_account(
        db=db,
        email=str(request.email),
        password=request.password,
    )

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