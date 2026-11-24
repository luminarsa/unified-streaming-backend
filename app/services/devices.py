
import os
import secrets

from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.identity import (
    Account,
    Profile,
    RegisteredDevice,
    ProfileLockAuthorizationGrant,
)

from app.utils.auth import (
    hash_password,
    verify_password,
    hash_token,
    now_utc,
)


# =========================================================
# CONFIGURATION
# =========================================================

PROFILE_LOCK_GRANT_EXPIRY_MINUTES = 2
PROFILE_LOCK_OPERATION = "set_profile_lock"


def get_profile_lock_pin_pepper() -> str:
    """
    Get the secret pepper used when hashing profile-lock PINs.

    This must be configured in the environment.
    """

    pepper = os.getenv("PROFILE_LOCK_PIN_PEPPER")

    if not pepper:
        raise RuntimeError(
            "PROFILE_LOCK_PIN_PEPPER is missing from the environment."
        )

    return pepper


def hash_profile_lock_pin(pin: str) -> str:
    pepper = get_profile_lock_pin_pepper()
    return hash_password(f"{pepper}:{pin}")


def verify_profile_lock_pin_hash(pin: str, encoded_hash: str) -> bool:
    pepper = get_profile_lock_pin_pepper()
    return verify_password(f"{pepper}:{pin}", encoded_hash)


# =========================================================
# INTERNAL HELPERS
# =========================================================

def get_account_or_404(db: Session, account_id: UUID) -> Account:
    account = db.get(Account, account_id)

    if account is None:
        raise HTTPException(
            status_code=404,
            detail="Account not found.",
        )

    return account


def get_device_or_404(
    db: Session,
    account_id: UUID,
    device_id: UUID,
) -> RegisteredDevice:

    device = db.execute(
        select(RegisteredDevice).where(
            RegisteredDevice.id == device_id,
            RegisteredDevice.account_id == account_id,
        )
    ).scalar_one_or_none()

    if device is None:
        raise HTTPException(
            status_code=404,
            detail="Registered device not found.",
        )

    return device



# =========================================================
# DEVICE REGISTRATION
# =========================================================

def register_device(
    db: Session,
    account_id: UUID,
    device_installation_id: UUID,
    device_type: str,
) -> RegisteredDevice:
    """
    Register or identify a device installation.

    New devices receive a temporary name and require the
    account owner to provide a recognisable device name.

    Existing device names and confirmation status are preserved.
    """

    current_time = now_utc()

    statement = (
        insert(RegisteredDevice)
        .values(
            account_id=account_id,
            device_installation_id=device_installation_id,
            device_name="New device",
            device_type=device_type,
            is_name_confirmed=False,
            last_seen_at=current_time,
        )
        .on_conflict_do_update(
            index_elements=[
                RegisteredDevice.account_id,
                RegisteredDevice.device_installation_id,
            ],
            set_={
                "last_seen_at": current_time,
                "device_type": device_type,
                "updated_at": current_time,
            },
        )
        .returning(RegisteredDevice)
    )

    device = db.execute(statement).scalar_one()

    db.commit()
    db.refresh(device)

    return device


# =========================================================
# LIST REGISTERED DEVICES
# =========================================================

def list_registered_devices(
    db: Session,
    account_id: UUID,
) -> list[RegisteredDevice]:

    devices = db.execute(
        select(RegisteredDevice)
        .where(RegisteredDevice.account_id == account_id)
        .order_by(RegisteredDevice.last_seen_at.desc())
    ).scalars().all()

    return list(devices)



# =========================================================
# RENAME DEVICE
# =========================================================

def rename_registered_device(
    db: Session,
    account_id: UUID,
    device_id: UUID,
    device_name: str,
) -> RegisteredDevice:

    device = get_device_or_404(
        db=db,
        account_id=account_id,
        device_id=device_id,
    )

    device_name = device_name.strip()

    if not device_name:
        raise HTTPException(
            status_code=422,
            detail="Device name cannot be empty.",
        )

    device.device_name = device_name
    device.is_name_confirmed = True
    device.updated_at = now_utc()

    db.commit()
    db.refresh(device)

    return device


# =========================================================
# DELETE DEVICE REGISTRATION
# =========================================================

def delete_registered_device(
    db: Session,
    account_id: UUID,
    device_id: UUID,
) -> None:

    device = get_device_or_404(
        db=db,
        account_id=account_id,
        device_id=device_id,
    )

    db.delete(device)
    db.commit()


# =========================================================
# CREATE PROFILE LOCK PIN
# =========================================================

def create_profile_lock_pin(
    db: Session,
    account_id: UUID,
    pin: str,
) -> Account:
    """
    Create the account-level Profile Lock PIN.

    This operation only works when the account does not already
    have a PIN configured.
    """

    account = get_account_or_404(db, account_id)

    if account.profile_lock_pin_hash:
        raise HTTPException(
            status_code=409,
            detail="A Profile Lock PIN already exists. Use the change PIN operation.",
        )

    account.profile_lock_pin_hash = hash_profile_lock_pin(pin)
    account.profile_lock_pin_updated_at = now_utc()

    db.commit()
    db.refresh(account)

    return account


# =========================================================
# CHANGE PROFILE LOCK PIN
# =========================================================

def change_profile_lock_pin(
    db: Session,
    account_id: UUID,
    current_pin: str,
    new_pin: str,
) -> Account:

    account = get_account_or_404(db, account_id)

    if not account.profile_lock_pin_hash:
        raise HTTPException(
            status_code=409,
            detail="No Profile Lock PIN has been configured.",
        )

    if not verify_profile_lock_pin_hash(
        current_pin,
        account.profile_lock_pin_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="The current Profile Lock PIN is incorrect.",
        )

    account.profile_lock_pin_hash = hash_profile_lock_pin(new_pin)
    account.profile_lock_pin_updated_at = now_utc()

    db.commit()
    db.refresh(account)

    return account


# =========================================================
# VERIFY PROFILE LOCK PIN
# =========================================================

def verify_profile_lock_pin(
    db: Session,
    account_id: UUID,
    pin: str,
    device_id: UUID,
    operation: str,
) -> dict:
    """
    Verify the account PIN and issue a short-lived,
    single-use authorization grant for a specific device.
    """

    if operation != PROFILE_LOCK_OPERATION:
        raise HTTPException(
            status_code=400,
            detail="Unsupported Profile Lock operation.",
        )

    account = get_account_or_404(db, account_id)

    if not account.profile_lock_pin_hash:
        raise HTTPException(
            status_code=409,
            detail="A Profile Lock PIN has not been configured.",
        )

    device = get_device_or_404(
        db=db,
        account_id=account_id,
        device_id=device_id,
    )

    if not verify_profile_lock_pin_hash(
        pin,
        account.profile_lock_pin_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Incorrect Profile Lock PIN.",
        )

    raw_grant = secrets.token_urlsafe(32)

    grant = ProfileLockAuthorizationGrant(
        account_id=account_id,
        device_id=device.id,
        grant_hash=hash_token(raw_grant),
        operation=operation,
        expires_at=now_utc() + timedelta(
            minutes=PROFILE_LOCK_GRANT_EXPIRY_MINUTES
        ),
    )

    db.add(grant)
    db.commit()

    return {
        "authorization_grant": raw_grant,
        "expires_in_seconds": (
            PROFILE_LOCK_GRANT_EXPIRY_MINUTES * 60
        ),
    }


# =========================================================
# SET OR REMOVE DEVICE PROFILE LOCK
# =========================================================

def set_device_profile_lock(
    db: Session,
    account_id: UUID,
    device_id: UUID,
    profile_id: UUID | None,
    authorization_grant: str,
) -> RegisteredDevice:
    """
    Set or remove a device's assigned profile.

    A valid authorization grant is required for both operations.

    The grant is locked and consumed in the same transaction
    that updates the device.
    """

    try:
        device = get_device_or_404(
            db=db,
            account_id=account_id,
            device_id=device_id,
        )

        grant = db.execute(
            select(ProfileLockAuthorizationGrant)
            .where(
                ProfileLockAuthorizationGrant.account_id == account_id,
                ProfileLockAuthorizationGrant.device_id == device_id,
                ProfileLockAuthorizationGrant.grant_hash == hash_token(
                    authorization_grant
                ),
                ProfileLockAuthorizationGrant.operation == PROFILE_LOCK_OPERATION,
                ProfileLockAuthorizationGrant.used_at.is_(None),
                ProfileLockAuthorizationGrant.expires_at > now_utc(),
            )
            .with_for_update()
        ).scalar_one_or_none()

        if grant is None:
            raise HTTPException(
                status_code=403,
                detail="Invalid, expired, or already-used authorization grant.",
            )

        if profile_id is not None:
            profile = db.execute(
                select(Profile).where(
                    Profile.id == profile_id,
                    Profile.account_id == account_id,
                )
            ).scalar_one_or_none()

            if profile is None:
                raise HTTPException(
                    status_code=404,
                    detail="The selected profile does not belong to this account.",
                )

        grant.used_at = now_utc()
        device.locked_profile_id = profile_id
        device.updated_at = now_utc()

        db.commit()
        db.refresh(device)

        return device

    except Exception:
        db.rollback()
        raise
