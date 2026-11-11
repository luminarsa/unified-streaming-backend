
import base64
import hashlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


def _get_encryption_key() -> bytes:
    """
    Load and validate the AES-256 encryption key.
    """

    encoded_key = settings.payment_encryption_key

    if not encoded_key:
        raise RuntimeError(
            "PAYMENT_ENCRYPTION_KEY is missing from environment settings."
        )

    try:
        key = base64.b64decode(encoded_key, validate=True)
    except Exception as exc:
        raise RuntimeError(
            "PAYMENT_ENCRYPTION_KEY must be valid Base64."
        ) from exc

    if len(key) != 32:
        raise RuntimeError(
            "PAYMENT_ENCRYPTION_KEY must decode to exactly 32 bytes."
        )

    return key


def encrypt_payment_token(token: str) -> str:
    """
    Encrypt a PayPal payment token.

    Returns a Base64 string containing:
    nonce + encrypted token + authentication tag.
    """

    if not token:
        raise ValueError("Payment token cannot be empty.")

    key = _get_encryption_key()
    nonce = AESGCM.generate_key(bit_length=96) if False else None

    # AES-GCM requires a fresh 12-byte nonce for every encryption.
    import os
    nonce = os.urandom(12)

    aes = AESGCM(key)

    encrypted = aes.encrypt(
        nonce,
        token.encode("utf-8"),
        None,
    )

    combined = nonce + encrypted

    return base64.b64encode(combined).decode("utf-8")


def decrypt_payment_token(encrypted_token: str) -> str:
    """
    Decrypt a previously encrypted PayPal payment token.
    """

    key = _get_encryption_key()

    try:
        combined = base64.b64decode(
            encrypted_token,
            validate=True,
        )

        nonce = combined[:12]
        encrypted = combined[12:]

        aes = AESGCM(key)

        decrypted = aes.decrypt(
            nonce,
            encrypted,
            None,
        )

        return decrypted.decode("utf-8")

    except Exception as exc:
        raise RuntimeError(
            "Unable to decrypt payment token. Check the encryption key and stored data."
        ) from exc


def fingerprint_payment_token(token: str) -> str:
    """
    Create a one-way fingerprint for duplicate detection.
    This is not used to recover the token.
    """

    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()
