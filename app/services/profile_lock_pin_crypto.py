
import os

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status


def get_profile_lock_pin_fernet():
    """
    Load the Profile Lock PIN encryption key.
    """

    encryption_key = os.getenv(
        "PROFILE_LOCK_PIN_ENCRYPTION_KEY"
    )

    if not encryption_key:
        raise RuntimeError(
            "PROFILE_LOCK_PIN_ENCRYPTION_KEY is not configured."
        )

    try:
        return Fernet(encryption_key.encode())

    except Exception as exc:
        raise RuntimeError(
            "PROFILE_LOCK_PIN_ENCRYPTION_KEY is invalid."
        ) from exc


def encrypt_profile_lock_pin(pin: str) -> str:
    """
    Encrypt a Profile Lock PIN so it can be retrieved later.
    """

    fernet = get_profile_lock_pin_fernet()

    encrypted_pin = fernet.encrypt(
        pin.encode("utf-8")
    )

    return encrypted_pin.decode("utf-8")


def decrypt_profile_lock_pin(encrypted_pin: str) -> str:
    """
    Decrypt a stored Profile Lock PIN.
    """

    fernet = get_profile_lock_pin_fernet()

    try:
        decrypted_pin = fernet.decrypt(
            encrypted_pin.encode("utf-8")
        )

        return decrypted_pin.decode("utf-8")

    except InvalidToken:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to decrypt the stored Profile Lock PIN.",
        )
