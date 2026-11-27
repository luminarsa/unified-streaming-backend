
import hmac
import logging
import re

from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models.commercial import Card2CryptoPayment

from app.services.payment_security import (
    fingerprint_payment_token,
)

from app.services.card2crypto.payment_processor import (
    process_card2crypto_payment,
)


logger = logging.getLogger(__name__)


SUPPORTED_COINS = {
    "polygon_usdc",
    "polygon_usdt",
}

TXID_PATTERN = re.compile(r"^0x[a-fA-F0-9]{64}$")


def _validate_positive_amount(
    value: str,
    field_name: str,
) -> Decimal:
    """
    Validate a positive decimal amount received from Card2Crypto.
    """

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            f"Invalid {field_name} received from Card2Crypto."
        )

    if not amount.is_finite() or amount <= 0:
        raise ValueError(
            f"Invalid {field_name} received from Card2Crypto."
        )

    return amount


def handle_card2crypto_callback(
    db: Session,
    number: str,
    callback_token: str,
    value_coin: str,
    coin: str,
    txid_in: str,
    txid_out: str,
    address_in: str,
    value_forwarded_coin: str | None = None,
) -> dict:
    """
    Authenticate and process a Card2Crypto payment callback.

    Card2Crypto sends this information through a GET request.
    The callback token and receiving address must match the
    information stored during checkout.
    """

    if not number:
        raise ValueError("Payment reference is missing.")

    if not callback_token:
        raise ValueError("Callback authentication token is missing.")

    # --------------------------------------------------
    # 1. Find and lock the Card2Crypto payment.
    # --------------------------------------------------

    payment = (
        db.query(Card2CryptoPayment)
        .filter(
            Card2CryptoPayment.payment_reference == number
        )
        .with_for_update()
        .first()
    )

    if not payment:
        raise ValueError(
            "Card2Crypto payment reference was not found."
        )

    # --------------------------------------------------
    # 2. Authenticate the callback token.
    # --------------------------------------------------

    received_token_hash = fingerprint_payment_token(
        callback_token
    )

    if not hmac.compare_digest(
        payment.callback_token_hash,
        received_token_hash,
    ):
        logger.warning(
            "Invalid Card2Crypto callback token. Reference: %s",
            number,
        )

        raise ValueError(
            "Card2Crypto callback authentication failed."
        )

    # --------------------------------------------------
    # 3. Validate receiving address.
    # --------------------------------------------------

    if not address_in:
        raise ValueError(
            "Card2Crypto receiving address is missing."
        )

    if (
        payment.polygon_address_in.lower()
        != address_in.lower()
    ):
        logger.warning(
            "Card2Crypto receiving address mismatch. Reference: %s",
            number,
        )

        raise ValueError(
            "Card2Crypto receiving address does not match."
        )

    # --------------------------------------------------
    # 4. Validate payment coin.
    # --------------------------------------------------

    normalized_coin = coin.lower().strip()

    if normalized_coin not in SUPPORTED_COINS:
        raise ValueError(
            "Unsupported Card2Crypto payment coin."
        )

    # --------------------------------------------------
    # 5. Validate blockchain transaction hashes.
    # --------------------------------------------------

    if not TXID_PATTERN.fullmatch(txid_in or ""):
        raise ValueError(
            "Invalid incoming blockchain transaction ID."
        )

    if not TXID_PATTERN.fullmatch(txid_out or ""):
        raise ValueError(
            "Invalid outgoing blockchain transaction ID."
        )

    # --------------------------------------------------
    # 6. Validate payment amount.
    # --------------------------------------------------

    received_amount = _validate_positive_amount(
        value_coin,
        "payment amount",
    )

    forwarded_amount = None

    if value_forwarded_coin is not None:
        try:
            forwarded_amount = Decimal(
                str(value_forwarded_coin)
            )
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(
                "Invalid forwarded payment amount."
            )

        if (
            not forwarded_amount.is_finite()
            or forwarded_amount < 0
        ):
            raise ValueError(
                "Invalid forwarded payment amount."
            )

    # --------------------------------------------------
    # 7. Pass the authenticated callback to processor.
    # --------------------------------------------------

    logger.info(
        "Authenticated Card2Crypto callback received. Reference: %s",
        number,
    )

    return process_card2crypto_payment(
        db=db,
        payment_reference=number,
        value_coin=str(received_amount),
        coin=normalized_coin,
        txid_in=txid_in,
        txid_out=txid_out,
        value_forwarded_coin=(
            str(forwarded_amount)
            if forwarded_amount is not None
            else None
        ),
    )
