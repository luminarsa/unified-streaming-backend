
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PlanCreateRequest(BaseModel):

    # Basic plan information
    category: str | None = Field(default=None, max_length=40)
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)

    # Pricing
    price_minor: int = Field(ge=0, strict=True)
    currency: Literal["ZAR"] = "ZAR"

    paypal_price: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=2,
    )

    paypal_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
    )

    # Subscription configuration
    billing_interval: str = Field(
        default="Monthly",
        max_length=20,
    )

    max_simultaneous_streams: int = Field(
        default=1,
        ge=1,
        strict=True,
    )

    is_active: bool = True

    # Platform entitlements
    # Empty list means all active platforms.
    entitlements: list[UUID] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        value = value.strip().upper()

        if not value:
            raise ValueError("Plan code cannot be empty.")

        return value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Plan name cannot be empty.")

        return value

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("Category cannot be empty.")

        return value

    @field_validator("paypal_currency")
    @classmethod
    def normalize_paypal_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return value.strip().upper()

    @field_validator("entitlements")
    @classmethod
    def validate_entitlements(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Duplicate platform IDs are not allowed.")

        return value


# -----------------------------------------
# RESPONSE SCHEMAS
# -----------------------------------------

class PlanPlatformResponse(BaseModel):
    id: UUID
    name: str
    slug: str


class PlanDataResponse(BaseModel):
    id: UUID

    category: str | None
    code: str
    name: str

    price_minor: int
    price_zar: str
    currency: str

    paypal_price: Decimal | None
    paypal_currency: str | None

    billing_interval: str
    max_simultaneous_streams: int
    is_active: bool

    entitlements: list[PlanPlatformResponse]

    created_at: datetime | None


class PlanCreateResponse(BaseModel):
    success: bool
    message: str
    data: PlanDataResponse
