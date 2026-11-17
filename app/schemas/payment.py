from pydantic import BaseModel, Field


class SubscriptionCheckoutRequest(BaseModel):
    plan_id: str = Field(..., min_length=36, max_length=36)
    idempotency_key: str = Field(..., min_length=1, max_length=100)