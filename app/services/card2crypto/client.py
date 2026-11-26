
import logging

from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import httpx


logger = logging.getLogger(__name__)


CARD2CRYPTO_API_BASE_URL = "https://api.card2crypto.org/control"
CARD2CRYPTO_CONVERSION_URL = f"{CARD2CRYPTO_API_BASE_URL}/convert.php"
CARD2CRYPTO_WALLET_URL = f"{CARD2CRYPTO_API_BASE_URL}/wallet.php"
CARD2CRYPTO_PAYMENT_STATUS_URL = (
    "https://card2crypto.org/control/payment-status.php"
)

CARD2CRYPTO_TIMEOUT = 40.0


class Card2CryptoError(Exception):
    """Raised when a Card2Crypto API request fails."""


def _to_decimal(value: str | int | float | Decimal) -> Decimal:
    """
    Convert a numeric value into Decimal without using float arithmetic.
    """

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise Card2CryptoError("Invalid numeric value supplied to Card2Crypto.")

    if not result.is_finite() or result <= 0:
        raise Card2CryptoError("The amount must be greater than zero.")

    return result


async def convert_zar_to_usd(
    zar_amount: Decimal,
) -> dict:
    """
    Convert a ZAR amount into USD using Card2Crypto.

    Returns:
        {
            "zar_amount": Decimal,
            "usd_amount": Decimal,
            "exchange_rate": Decimal
        }
    """

    zar_amount = _to_decimal(zar_amount)

    params = {
        "from": "ZAR",
        "value": str(zar_amount),
    }

    try:
        async with httpx.AsyncClient(
            timeout=CARD2CRYPTO_TIMEOUT
        ) as client:
            response = await client.get(
                CARD2CRYPTO_CONVERSION_URL,
                params=params,
            )

            response.raise_for_status()
            data = response.json()

    except httpx.HTTPError as exc:
        logger.exception("Card2Crypto currency conversion request failed.")
        raise Card2CryptoError(
            "Unable to contact Card2Crypto currency conversion service."
        ) from exc

    except ValueError as exc:
        raise Card2CryptoError(
            "Card2Crypto returned an invalid conversion response."
        ) from exc

    if not isinstance(data, dict) or data.get("status") != "success":
        raise Card2CryptoError(
            "Card2Crypto could not convert the supplied ZAR amount."
        )

    try:
        usd_amount = _to_decimal(data["value_coin"])
        exchange_rate = _to_decimal(data["exchange_rate"])

    except (KeyError, TypeError) as exc:
        raise Card2CryptoError(
            "Card2Crypto conversion response is missing required values."
        ) from exc

    return {
        "zar_amount": zar_amount,
        "usd_amount": usd_amount,
        "exchange_rate": exchange_rate,
    }


async def create_payment_wallet(
    merchant_wallet: str,
    callback_url: str,
) -> dict:
    """
    Generate a temporary Card2Crypto payment wallet.

    Card2Crypto's example uses a triple-URL-encoded callback parameter.
    We encode it twice here; httpx performs the third encoding when
    constructing the query string.

    Returns:
        {
            "address_in": str,
            "polygon_address_in": str,
            "callback_url": str,
            "ipn_token": str
        }
    """

    if not merchant_wallet or not merchant_wallet.startswith("0x"):
        raise Card2CryptoError(
            "A valid Polygon merchant wallet address is required."
        )

    if len(merchant_wallet) != 42:
        raise Card2CryptoError(
            "The Polygon merchant wallet address has an invalid length."
        )

    if not callback_url.startswith("https://"):
        raise Card2CryptoError(
            "The Card2Crypto callback URL must use HTTPS."
        )

    callback_encoded_twice = quote(
        quote(callback_url, safe=""),
        safe="",
    )

    params = {
        "address": merchant_wallet,
        "callback": callback_encoded_twice,
    }

    try:
        async with httpx.AsyncClient(
            timeout=CARD2CRYPTO_TIMEOUT
        ) as client:
            response = await client.get(
                CARD2CRYPTO_WALLET_URL,
                params=params,
            )

            response.raise_for_status()
            data = response.json()

    except httpx.HTTPError as exc:
        logger.exception("Card2Crypto wallet creation request failed.")
        raise Card2CryptoError(
            "Unable to create a Card2Crypto payment wallet."
        ) from exc

    except ValueError as exc:
        raise Card2CryptoError(
            "Card2Crypto returned an invalid wallet response."
        ) from exc

    required_fields = (
        "address_in",
        "polygon_address_in",
        "callback_url",
        "ipn_token",
    )

    if not isinstance(data, dict):
        raise Card2CryptoError(
            "Card2Crypto returned an invalid wallet response."
        )

    missing_fields = [
        field for field in required_fields
        if not data.get(field)
    ]

    if missing_fields:
        logger.error(
            "Card2Crypto wallet response is missing required fields: %s",
            ", ".join(missing_fields),
        )
        raise Card2CryptoError(
            "Card2Crypto wallet response is incomplete."
        )

    return {
        "address_in": data["address_in"],
        "polygon_address_in": data["polygon_address_in"],
        "callback_url": data["callback_url"],
        "ipn_token": data["ipn_token"],
    }


async def check_payment_status(ipn_token: str) -> dict:
    """
    Check a Card2Crypto payment's status.

    This is intended for manual or exceptional reconciliation.
    Normal subscription activation must be driven by the callback.
    """

    if not ipn_token:
        raise Card2CryptoError(
            "A Card2Crypto IPN token is required."
        )

    params = {
        "ipn_token": ipn_token,
    }

    try:
        async with httpx.AsyncClient(
            timeout=CARD2CRYPTO_TIMEOUT
        ) as client:
            response = await client.get(
                CARD2CRYPTO_PAYMENT_STATUS_URL,
                params=params,
            )

            response.raise_for_status()
            data = response.json()

    except httpx.HTTPError as exc:
        logger.exception("Card2Crypto payment status request failed.")
        raise Card2CryptoError(
            "Unable to check Card2Crypto payment status."
        ) from exc

    except ValueError as exc:
        raise Card2CryptoError(
            "Card2Crypto returned an invalid payment status response."
        ) from exc

    if not isinstance(data, dict):
        raise Card2CryptoError(
            "Card2Crypto returned an invalid payment status response."
        )

    return data
