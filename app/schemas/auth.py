from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class PrimaryProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    is_kids_profile: bool = False
    avatar_key: str | None = Field(default=None, max_length=120)

class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=128)
    primary_profile: PrimaryProfileCreate

class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)
    revoke_session_id: UUID | None = None

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
