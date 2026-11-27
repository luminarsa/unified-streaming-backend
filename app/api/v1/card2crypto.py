
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_account_id, get_db
from app.services.card2crypto.checkout import create_card2crypto_checkout
from app.services.card2crypto.client import Card2CryptoError
from app.services.card2crypto.callback import handle_card2crypto_callback


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/card2crypto",
    tags=["Card2Crypto"],
)


class Card2CryptoCheckoutRequest(BaseModel):
    plan_id: UUID
    idempotency_key: str = Field(..., min_length=1, max_length=100)



@router.post(
    "/checkout",
    status_code=status.HTTP_201_CREATED,
)
async def create_card2crypto_checkout_endpoint(
    payload: Card2CryptoCheckoutRequest,
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> dict:
    """
    Create a pending subscription and return the Card2Crypto checkout URL.
    """

    try:
        result = await create_card2crypto_checkout(
            db=db,
            account_id=UUID(str(account_id)),
            plan_id=payload.plan_id,
            idempotency_key=payload.idempotency_key,
        )

        return result

    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    except Card2CryptoError:
        db.rollback()
        logger.exception("Card2Crypto checkout provider request failed")

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Card2Crypto could not create the checkout session.",
        )

    except Exception:
        db.rollback()
        logger.exception("Unexpected Card2Crypto checkout error")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create Card2Crypto checkout.",
        )


@router.get("/callback")
def card2crypto_payment_callback(
    number: str,
    callback_token: str,
    value_coin: str,
    coin: str,
    txid_in: str,
    txid_out: str,
    address_in: str,
    value_forwarded_coin: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Receive Card2Crypto's payment notification.

    This endpoint is called by Card2Crypto, so it does not require
    the customer's normal login token.
    """

    try:
        handle_card2crypto_callback(
            db=db,
            number=number,
            callback_token=callback_token,
            value_coin=value_coin,
            coin=coin,
            txid_in=txid_in,
            txid_out=txid_out,
            address_in=address_in,
            value_forwarded_coin=value_forwarded_coin,
        )

        # Card2Crypto expects a successful HTTP response.
        return Response(status_code=status.HTTP_200_OK)

    except ValueError as exc:
        db.rollback()

        logger.warning(
            "Card2Crypto callback rejected for reference %s: %s",
            number,
            str(exc),
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    except Exception:
        db.rollback()
        logger.exception(
            "Unexpected Card2Crypto callback error for reference %s",
            number,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to process Card2Crypto callback.",
        )
