
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.v1.dependencies import get_active_profile
from app.models.identity import Profile

from app.schemas.payments import (
    CreateCheckoutRequest,
    CreateCheckoutResponse,
    CapturePaymentRequest,
    CapturePaymentResponse,
)

from app.services.payments import (
    create_checkout,
    capture_checkout,
)


router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


@router.post(
    "/checkout",
    response_model=CreateCheckoutResponse,
)
async def checkout(
    request: CreateCheckoutRequest,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    result = await create_checkout(
        db=db,
        profile=profile,
        plan_id=request.plan_id,
    )

    return result


@router.post(
    "/capture",
    response_model=CapturePaymentResponse,
)
async def capture(
    request: CapturePaymentRequest,
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    result = await capture_checkout(
        db=db,
        profile=profile,
        order_id=request.order_id,
    )

    return result
