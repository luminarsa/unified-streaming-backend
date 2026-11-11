
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class CreateCheckoutRequest(BaseModel):
    plan_id: str


class CreateCheckoutResponse(BaseModel):
    order_id: str
    subscription_id: str
    status: str
    currency: str
    amount: str


class CapturePaymentRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)


class CapturePaymentResponse(BaseModel):
    order_id: str
    subscription_id: str
    payment_status: str
    subscription_status: str


class PaymentMethodResponse(BaseModel):
    id: str
    provider: str
    card_brand: Optional[str] = None
    last_four: Optional[str] = None
    expiry_month: Optional[int] = None
    expiry_year: Optional[int] = None
    is_default: bool

    model_config = ConfigDict(from_attributes=True)
