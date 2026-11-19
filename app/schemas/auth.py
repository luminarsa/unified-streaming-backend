
from datetime import datetime
from uuid import UUID
import re

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    field_validator,
    model_validator,
)


# =================================================
# REGISTRATION SCHEMAS
# =================================================

class PrimaryProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)

    is_kids_profile: bool = False

    avatar_url: str | None = Field(
        default=None,
        max_length=500,
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Profile name cannot be empty.")

        return value


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    phone_number: str = Field(
        min_length=9,
        max_length=20,
    )

    password: str = Field(
        min_length=10,
        max_length=128,
    )

    confirm_password: str = Field(
        min_length=10,
        max_length=128,
    )

    referral_code: str | None = Field(
        default=None,
        min_length=3,
        max_length=15,
    )

    primary_profile: PrimaryProfileCreate

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()

        if not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            value,
        ):
            raise ValueError("Please provide a valid email address.")

        return value

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        value = value.strip()

        if not re.fullmatch(r"\+[1-9]\d{7,14}", value):
            raise ValueError(
                "Phone number must include its international "
                "calling code, for example +27821234567."
            )

        return value

    @field_validator("referral_code")
    @classmethod
    def clean_referral_code(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip().upper()

        return value or None

    @model_validator(mode="after")
    def validate_password_confirmation(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")

        return self


class VerifyRegistrationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    verification_code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ResendVerificationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


# =================================================
# REGISTRATION RESPONSE SCHEMAS
# =================================================

class RegistrationResponse(BaseModel):
    success: bool
    message: str
    email: str
    verification_required: bool
    expires_in_minutes: int


class RegistrationVerificationResponse(BaseModel):
    success: bool
    message: str
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    account_id: str
    profile_selection_required: bool


class ResendVerificationResponse(BaseModel):
    success: bool
    message: str
    expires_in_minutes: int


# =================================================
# LOGIN AND PROFILE SELECTION
# =================================================

class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)
    revoke_session_id: UUID | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class SelectProfileRequest(BaseModel):
    profile_id: UUID


class ProfileSummary(BaseModel):
    id: UUID
    name: str
    is_kids_profile: bool
    avatar_key: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AccountSummary(BaseModel):
    id: UUID
    email: str
    status: str


class SubscriptionSummary(BaseModel):
    plan_code: str
    plan_name: str
    status: str
    price_minor: int
    currency: str
    billing_interval: str
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    session_id: UUID
    account: AccountSummary
    active_profile: ProfileSummary
    subscription: SubscriptionSummary | None = None


# =================================================
# SESSION SCHEMAS
# =================================================

class SessionSummary(BaseModel):
    id: UUID
    device_name: str | None = None
    user_agent: str | None = None
    created_at: datetime
    last_seen_at: datetime | None = None
    expires_at: datetime
    current: bool = False


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    max_devices: int
    active_devices: int


# =================================================
# PLAN AND SUBSCRIPTION SCHEMAS
# =================================================

class PlanResponse(BaseModel):
    code: str
    name: str
    price_minor: int
    currency: str
    billing_interval: str
    max_devices: int
    is_active: bool


class CurrentSubscriptionResponse(BaseModel):
    subscription: SubscriptionSummary | None


class SelectPlanRequest(BaseModel):
    plan_code: str = Field(min_length=2, max_length=40)
