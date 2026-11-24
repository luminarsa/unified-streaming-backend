
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db

from app.api.v1.dependencies import get_current_session

from app.schemas.auth import (
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    DeviceListResponse,
    RenameDeviceRequest,
    RenameDeviceResponse,
    SetDeviceProfileLockRequest,
    SetDeviceProfileLockResponse,
    CreateProfileLockPinRequest,
    ChangeProfileLockPinRequest,
    ProfileLockPinResponse,
    VerifyProfileLockPinRequest,
    VerifyProfileLockPinResponse,
)

from app.services.devices import (
    register_device,
    list_registered_devices,
    rename_registered_device,
    delete_registered_device,
    create_profile_lock_pin,
    change_profile_lock_pin,
    verify_profile_lock_pin,
    set_device_profile_lock,
)


router = APIRouter()


# =========================================================
# HELPER
# =========================================================

def get_account_id(current_session: dict) -> UUID:
    return UUID(str(current_session["account_id"]))



# =================================================
# REGISTER OR IDENTIFY DEVICE
# =================================================

@router.post(
    "/register",
    response_model=DeviceRegisterResponse,
    status_code=status.HTTP_200_OK,
)
def register_new_device(
    payload: DeviceRegisterRequest,
    current_session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    device = register_device(
        db=db,
        account_id=get_account_id(current_session),
        device_installation_id=payload.device_installation_id,
        device_type=payload.device_type,
    )

    requires_name = not device.is_name_confirmed

    return {
        "success": True,
        "message": (
            "Please provide a name for this device."
            if requires_name
            else "Device identified successfully."
        ),
        "requires_name": requires_name,
        "device": device,
    }


# =========================================================
# LIST REGISTERED DEVICES
# =========================================================

@router.get(
    "",
    response_model=DeviceListResponse,
)
def get_registered_devices(
    current_session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    devices = list_registered_devices(
        db=db,
        account_id=get_account_id(current_session),
    )

    return {
        "devices": devices,
        "total_devices": len(devices),
    }


# =========================================================
# RENAME DEVICE
# =========================================================

@router.patch(
    "/{device_id}/name",
    response_model=RenameDeviceResponse,
)
def rename_device(
    device_id: UUID,
    payload: RenameDeviceRequest,
    current_session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    device = rename_registered_device(
        db=db,
        account_id=get_account_id(current_session),
        device_id=device_id,
        device_name=payload.device_name,
    )

    return {
        "success": True,
        "message": "Device renamed successfully.",
        "device": device,
    }


# =========================================================
# DELETE DEVICE
# =========================================================

@router.delete(
    "/{device_id}",
    status_code=status.HTTP_200_OK,
)
def remove_registered_device(
    device_id: UUID,
    current_session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    delete_registered_device(
        db=db,
        account_id=get_account_id(current_session),
        device_id=device_id,
    )

    return {
        "success": True,
        "message": "Device registration removed successfully.",
    }


# =========================================================
# CREATE PROFILE LOCK PIN
# =========================================================

@router.post(
    "/profile-lock-pin",
    response_model=ProfileLockPinResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_account_profile_lock_pin(
    payload: CreateProfileLockPinRequest,
    current_session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    create_profile_lock_pin(
        db=db,
        account_id=get_account_id(current_session),
        pin=payload.pin,
    )

    return {
        "success": True,
        "message": "Profile Lock PIN created successfully.",
    }


# =========================================================
# CHANGE PROFILE LOCK PIN
# =========================================================

@router.put(
    "/profile-lock-pin",
    response_model=ProfileLockPinResponse,
)
def update_account_profile_lock_pin(
    payload: ChangeProfileLockPinRequest,
    current_session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    change_profile_lock_pin(
        db=db,
        account_id=get_account_id(current_session),
        current_pin=payload.current_pin,
        new_pin=payload.new_pin,
    )

    return {
        "success": True,
        "message": "Profile Lock PIN changed successfully.",
    }


# =========================================================
# VERIFY PROFILE LOCK PIN
# =========================================================

@router.post(
    "/profile-lock-pin/verify",
    response_model=VerifyProfileLockPinResponse,
)
def verify_account_profile_lock_pin(
    payload: VerifyProfileLockPinRequest,
    current_session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    result = verify_profile_lock_pin(
        db=db,
        account_id=get_account_id(current_session),
        pin=payload.pin,
        device_id=payload.device_id,
        operation=payload.operation,
    )

    return {
        "success": True,
        "message": "Profile Lock PIN verified successfully.",
        "authorization_grant": result["authorization_grant"],
        "expires_in_seconds": result["expires_in_seconds"],
    }


# =========================================================
# SET OR REMOVE DEVICE PROFILE LOCK
# =========================================================

@router.patch(
    "/{device_id}/profile-lock",
    response_model=SetDeviceProfileLockResponse,
)
def update_device_profile_lock(
    device_id: UUID,
    payload: SetDeviceProfileLockRequest,
    current_session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    device = set_device_profile_lock(
        db=db,
        account_id=get_account_id(current_session),
        device_id=device_id,
        profile_id=payload.profile_id,
        authorization_grant=payload.authorization_grant,
    )

    message = (
        "Device profile lock removed successfully."
        if payload.profile_id is None
        else "Device profile lock assigned successfully."
    )

    return {
        "success": True,
        "message": message,
        "device": device,
    }
