
import base64
import hashlib
import hmac
import uuid

from cryptography.fernet import Fernet, InvalidToken

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.payment_method import PaymentMethod
from app.models.identity import Profile

from app.services import paypal


# ---------------------------------------------------------
# 1. ENCRYPTION AND TOKEN SECURITY
# ---------------------------------------------------------

def _get_encryption_key() -> bytes:
    """
    Loads and validates the payment encryption key.

    The key must be a URL-safe Base64 encoded 32-byte key.
    """

    configured_key = settings.payment_encryption_key

    if not configured_key:
        raise RuntimeError(
            "PAYMENT_ENCRYPTION_KEY is missing from configuration."
        )

    try:
        decoded_key = base64.urlsafe_b64decode(
            configured_key.encode("utf-8")
        )

        if len(decoded_key) != 32:
            raise ValueError("Invalid encryption key length.")

        return configured_key.encode("utf-8")

    except Exception as exc:
        raise RuntimeError(
            "PAYMENT_ENCRYPTION_KEY is invalid."
        ) from exc


def _encrypt_token(token: str) -> str:
    """
    Encrypts a PayPal vault token before database storage.
    """

    if not token:
        raise ValueError("Payment token cannot be empty.")

    key = _get_encryption_key()

    cipher = Fernet(key)

    encrypted_token = cipher.encrypt(
        token.encode("utf-8")
    )

    return encrypted_token.decode("utf-8")


def _decrypt_token(encrypted_token: str) -> str:
    """
    Decrypts a stored PayPal vault token when needed
    for an authorized backend payment operation.
    """

    if not encrypted_token:
        raise ValueError("Encrypted payment token is missing.")

    key = _get_encryption_key()

    cipher = Fernet(key)

    try:
        decrypted_token = cipher.decrypt(
            encrypted_token.encode("utf-8")
        )

        return decrypted_token.decode("utf-8")

    except InvalidToken as exc:
        raise RuntimeError(
            "Unable to decrypt the saved payment token."
        ) from exc


def _get_token_fingerprint(token: str) -> str:
    """
    Generates a keyed fingerprint to detect duplicate tokens.

    The fingerprint is not the original PayPal vault token.
    """

    key = _get_encryption_key()

    decoded_key = base64.urlsafe_b64decode(key)

    fingerprint_key = hashlib.sha256(
        decoded_key + b"payment-method-fingerprint"
    ).digest()

    fingerprint = hmac.new(
        fingerprint_key,
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return fingerprint


# ---------------------------------------------------------
# 2. GET PAYMENT METHOD OWNED BY ACCOUNT
# ---------------------------------------------------------

def _get_payment_method(
    db: Session,
    profile: Profile,
    payment_method_id: str,
) -> PaymentMethod:

    try:
        method_uuid = uuid.UUID(payment_method_id)

    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail="Invalid payment method ID.",
        )

    payment_method = (
        db.query(PaymentMethod)
        .filter(
            PaymentMethod.id == method_uuid,
            PaymentMethod.account_id == profile.account_id,
        )
        .first()
    )

    if not payment_method:
        raise HTTPException(
            status_code=404,
            detail="Payment method not found.",
        )

    return payment_method


# ---------------------------------------------------------
# 3. FORMAT PAYMENT METHOD FOR FRONTEND
# ---------------------------------------------------------

def _payment_method_response(payment_method: PaymentMethod) -> dict:
    """
    Returns safe payment method information.

    Never returns the encrypted or decrypted vault token.
    """

    return {
        "id": str(payment_method.id),
        "provider": payment_method.provider,
        "card_brand": payment_method.card_brand,
        "last_four": payment_method.last_four,
        "expiry_month": payment_method.expiry_month,
        "expiry_year": payment_method.expiry_year,
        "status": payment_method.status,
        "is_default": payment_method.is_default,
        "created_at": payment_method.created_at,
    }


# ---------------------------------------------------------
# 4. LIST SAVED PAYMENT METHODS
# ---------------------------------------------------------

def list_payment_methods(
    db: Session,
    profile: Profile,
):
    """
    Returns all active saved payment methods belonging
    to the authenticated account.
    """

    payment_methods = (
        db.query(PaymentMethod)
        .filter(
            PaymentMethod.account_id == profile.account_id,
            PaymentMethod.status == "active",
        )
        .order_by(
            PaymentMethod.is_default.desc(),
            PaymentMethod.created_at.desc(),
        )
        .all()
    )

    return [
        _payment_method_response(method)
        for method in payment_methods
    ]


# ---------------------------------------------------------
# 5. SAVE A VERIFIED PAYPAL VAULT TOKEN
# ---------------------------------------------------------

async def save_payment_method(
    db: Session,
    account_id,
    vault_id: str,
    provider_customer_id: str | None = None,
    make_default: bool = False,
):
    """
    Saves a PayPal vault token.

    IMPORTANT:
    Call this only after the vault token has been received
    from a verified PayPal API response or verified webhook.

    The function retrieves card display information directly
    from PayPal instead of trusting frontend card details.
    """

    if not vault_id:
        raise HTTPException(
            status_code=400,
            detail="PayPal vault token is required.",
        )

    # Validate account ID.
    try:
        account_uuid = uuid.UUID(str(account_id))

    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail="Invalid account ID.",
        )

    # Retrieve the token information from PayPal.
    try:
        token_data = await paypal.get_payment_token(vault_id)

    except paypal.PayPalError as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve PayPal payment method.",
        ) from exc

    # PayPal payment token response contains payment source data.
    payment_source = token_data.get("payment_source", {})
    card_data = payment_source.get("card", {})

    if not card_data:
        raise HTTPException(
            status_code=400,
            detail="PayPal token does not contain card information.",
        )

    # Read non-sensitive card display information.
    card_brand = card_data.get("brand")
    last_four = card_data.get("last_digits")

    expiry_month = None
    expiry_year = None

    expiry = card_data.get("expiry")

    if expiry:
        try:
            expiry_parts = expiry.split("-")

            expiry_year = int(expiry_parts[0])
            expiry_month = int(expiry_parts[1])

        except (ValueError, IndexError, AttributeError):
            expiry_month = None
            expiry_year = None

    if last_four and (
        not isinstance(last_four, str)
        or len(last_four) != 4
        or not last_four.isdigit()
    ):
        last_four = None

    # Generate a secure fingerprint.
    fingerprint = _get_token_fingerprint(vault_id)

    # Prevent duplicate payment methods.
    existing_method = (
        db.query(PaymentMethod)
        .filter(
            PaymentMethod.account_id == account_uuid,
            PaymentMethod.provider == "paypal",
            PaymentMethod.token_fingerprint == fingerprint,
        )
        .first()
    )

    if existing_method:
        if existing_method.status == "active":
            return _payment_method_response(existing_method)

        raise HTTPException(
            status_code=409,
            detail="This payment method was previously removed.",
        )

    # Determine whether this should be the default card.
    existing_active_count = (
        db.query(PaymentMethod)
        .filter(
            PaymentMethod.account_id == account_uuid,
            PaymentMethod.status == "active",
        )
        .count()
    )

    should_be_default = (
        make_default or existing_active_count == 0
    )

    if should_be_default:
        (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.account_id == account_uuid,
                PaymentMethod.status == "active",
            )
            .update(
                {"is_default": False},
                synchronize_session=False,
            )
        )

    # Encrypt the PayPal vault token.
    encrypted_token = _encrypt_token(vault_id)

    payment_method = PaymentMethod(
        account_id=account_uuid,
        provider="paypal",
        provider_customer_id=provider_customer_id,
        encrypted_payment_token=encrypted_token,
        token_fingerprint=fingerprint,
        card_brand=card_brand,
        last_four=last_four,
        expiry_month=expiry_month,
        expiry_year=expiry_year,
        status="active",
        is_default=should_be_default,
    )

    try:
        db.add(payment_method)
        db.commit()
        db.refresh(payment_method)

    except Exception:
        db.rollback()
        raise

    return _payment_method_response(payment_method)


# ---------------------------------------------------------
# 6. SET DEFAULT PAYMENT METHOD
# ---------------------------------------------------------

def set_default_payment_method(
    db: Session,
    profile: Profile,
    payment_method_id: str,
):
    """
    Sets one of the account's active payment methods
    as the default payment method.
    """

    payment_method = _get_payment_method(
        db,
        profile,
        payment_method_id,
    )

    if payment_method.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Only active payment methods can be default.",
        )

    try:
        (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.account_id == profile.account_id,
                PaymentMethod.status == "active",
            )
            .update(
                {"is_default": False},
                synchronize_session=False,
            )
        )

        payment_method.is_default = True

        db.commit()
        db.refresh(payment_method)

    except Exception:
        db.rollback()
        raise

    return _payment_method_response(payment_method)


# ---------------------------------------------------------
# 7. GET DEFAULT PAYMENT METHOD TOKEN
# ---------------------------------------------------------

def get_default_payment_token(
    db: Session,
    account_id,
) -> tuple[PaymentMethod, str]:
    """
    Retrieves the default active payment method and
    decrypts its PayPal vault token.

    Internal backend use only.
    Never return this token to the frontend.
    """

    payment_method = (
        db.query(PaymentMethod)
        .filter(
            PaymentMethod.account_id == account_id,
            PaymentMethod.status == "active",
            PaymentMethod.is_default == True,
        )
        .first()
    )

    if not payment_method:
        raise HTTPException(
            status_code=404,
            detail="No default payment method is available.",
        )

    try:
        vault_id = _decrypt_token(
            payment_method.encrypted_payment_token
        )

    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to access the saved payment method.",
        ) from exc

    return payment_method, vault_id


# ---------------------------------------------------------
# 8. REMOVE SAVED PAYMENT METHOD
# ---------------------------------------------------------

async def delete_payment_method(
    db: Session,
    profile: Profile,
    payment_method_id: str,
):
    """
    Removes a saved payment method from PayPal and
    marks it as deleted in the local database.

    The token is never returned to the frontend.
    """

    payment_method = _get_payment_method(
        db,
        profile,
        payment_method_id,
    )

    if payment_method.status != "active":
        raise HTTPException(
            status_code=400,
            detail="This payment method is not active.",
        )

    # Decrypt the token for PayPal deletion.
    try:
        vault_id = _decrypt_token(
            payment_method.encrypted_payment_token
        )

    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to access the saved payment method.",
        ) from exc

    # Delete token from PayPal first.
    try:
        await paypal.delete_payment_token(vault_id)

    except paypal.PayPalError as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to remove payment method from PayPal.",
        ) from exc

    # Remember whether this was the default card
    # BEFORE changing its status.
    was_default = payment_method.is_default

    # Mark local payment method as deleted.
    payment_method.status = "deleted"
    payment_method.is_default = False
    payment_method.encrypted_payment_token = ""

    # Only select a replacement if the deleted card
    # was previously the default card.
    replacement = None

    if was_default:
        replacement = (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.account_id == profile.account_id,
                PaymentMethod.status == "active",
                PaymentMethod.id != payment_method.id,
            )
            .order_by(PaymentMethod.created_at.asc())
            .first()
        )

    if replacement:
        replacement.is_default = True
    try:
        db.commit()

    except Exception:
        db.rollback()
        raise

    return {
        "payment_method_id": str(payment_method.id),
        "status": "deleted",
        "message": "Payment method removed successfully.",
    }
