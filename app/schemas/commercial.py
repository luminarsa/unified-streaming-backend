
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SubscriptionCreate(BaseModel):
    plan_id: UUID


class SubscriptionResponse(BaseModel):
    id: UUID
    account_id: UUID
    plan_id: UUID
    status: str
    provider: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActiveSubscriptionResponse(BaseModel):
    subscription: SubscriptionResponse | None = None
    plan: dict | None = None

class PlanFeatureResponse(BaseModel):
    feature_code: str
    is_enabled: bool

class PlanResponse(BaseModel):
    id: UUID
    code: str
    name: str
    price_minor: int
    currency: str
    billing_interval: str
    is_active: bool
    max_simultaneous_streams: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlanDetailResponse(PlanResponse):
    platform_ids: list[UUID] = Field(default_factory=list)
    features: list[PlanFeatureResponse] = Field(default_factory=list)