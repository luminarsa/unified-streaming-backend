from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db

from app.schemas.platform import (
    PlatformCreate,
    PlatformUpdate,
    PlatformProfileCreate,
    PlatformProfileUpdate,
    PlatformProviderCreate,
    PlatformCompanyCreate,
    PlatformNetworkCreate,
    SliderCreate,
    SliderUpdate,
    PlatformNavigationCreate,
    PlatformLiveChannelCreate,
)

from app.services.platform import (
    create_platform,
    list_platforms,
    get_platform,
    update_platform,
    delete_platform,
    create_platform_profile,
    get_platform_profile,
    update_platform_profile,
    create_platform_provider,
    list_platform_providers,
    create_platform_company,
    list_platform_companies,
    create_platform_network,
    list_platform_networks,
    create_slider,
    list_platform_sliders,
    update_slider,
    create_navigation_item,
    list_platform_navigation,
    create_live_channel,
    list_platform_live_channels,
)


router = APIRouter(
    prefix="/platforms",
    tags=["Platforms"],
)


# --------------------------------------------------
# STREAMING PLATFORMS
# --------------------------------------------------

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_new_platform(
    data: PlatformCreate,
    db: Session = Depends(get_db),
):
    return create_platform(db, data)


@router.get("/")
def get_all_platforms(
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    return list_platforms(db, active_only=active_only)


@router.get("/{platform_id}")
def get_platform_details(
    platform_id: UUID,
    db: Session = Depends(get_db),
):
    return get_platform(db, platform_id)


@router.patch("/{platform_id}")
def update_platform_details(
    platform_id: UUID,
    data: PlatformUpdate,
    db: Session = Depends(get_db),
):
    return update_platform(db, platform_id, data)


@router.delete("/{platform_id}")
def remove_platform(
    platform_id: UUID,
    db: Session = Depends(get_db),
):
    return delete_platform(db, platform_id)


# --------------------------------------------------
# PLATFORM PROFILES
# --------------------------------------------------

@router.post("/profiles", status_code=status.HTTP_201_CREATED)
def create_new_platform_profile(
    data: PlatformProfileCreate,
    db: Session = Depends(get_db),
):
    return create_platform_profile(db, data)


@router.get("/{platform_id}/profile")
def get_platform_configuration(
    platform_id: UUID,
    db: Session = Depends(get_db),
):
    return get_platform_profile(db, platform_id)


@router.patch("/{platform_id}/profile")
def update_platform_configuration(
    platform_id: UUID,
    data: PlatformProfileUpdate,
    db: Session = Depends(get_db),
):
    return update_platform_profile(db, platform_id, data)


# --------------------------------------------------
# TMDB WATCH PROVIDERS
# --------------------------------------------------

@router.post("/providers", status_code=status.HTTP_201_CREATED)
def create_new_platform_provider(
    data: PlatformProviderCreate,
    db: Session = Depends(get_db),
):
    return create_platform_provider(db, data)


@router.get("/{platform_id}/providers")
def get_platform_provider_mappings(
    platform_id: UUID,
    db: Session = Depends(get_db),
):
    return list_platform_providers(db, platform_id)


# --------------------------------------------------
# TMDB COMPANIES / STUDIOS
# --------------------------------------------------

@router.post("/companies", status_code=status.HTTP_201_CREATED)
def create_new_platform_company(
    data: PlatformCompanyCreate,
    db: Session = Depends(get_db),
):
    return create_platform_company(db, data)


@router.get("/{platform_id}/companies")
def get_platform_company_mappings(
    platform_id: UUID,
    db: Session = Depends(get_db),
):
    return list_platform_companies(db, platform_id)


# --------------------------------------------------
# TMDB TV NETWORKS
# --------------------------------------------------

@router.post("/networks", status_code=status.HTTP_201_CREATED)
def create_new_platform_network(
    data: PlatformNetworkCreate,
    db: Session = Depends(get_db),
):
    return create_platform_network(db, data)


@router.get("/{platform_id}/networks")
def get_platform_network_mappings(
    platform_id: UUID,
    db: Session = Depends(get_db),
):
    return list_platform_networks(db, platform_id)


# --------------------------------------------------
# HOME PAGE SLIDERS
# --------------------------------------------------

@router.post("/sliders", status_code=status.HTTP_201_CREATED)
def create_new_slider(
    data: SliderCreate,
    db: Session = Depends(get_db),
):
    return create_slider(db, data)


@router.get("/{platform_id}/sliders")
def get_platform_slider_definitions(
    platform_id: UUID,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    return list_platform_sliders(
        db,
        platform_id,
        enabled_only=enabled_only,
    )


@router.patch("/sliders/{slider_id}")
def update_slider_definition(
    slider_id: UUID,
    data: SliderUpdate,
    db: Session = Depends(get_db),
):
    return update_slider(db, slider_id, data)


# --------------------------------------------------
# PLATFORM NAVIGATION
# --------------------------------------------------

@router.post("/navigation", status_code=status.HTTP_201_CREATED)
def create_new_navigation_item(
    data: PlatformNavigationCreate,
    db: Session = Depends(get_db),
):
    return create_navigation_item(db, data)


@router.get("/{platform_id}/navigation")
def get_platform_navigation_items(
    platform_id: UUID,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    return list_platform_navigation(
        db,
        platform_id,
        enabled_only=enabled_only,
    )


# --------------------------------------------------
# LIVE TV CHANNELS
# --------------------------------------------------

@router.post("/channels", status_code=status.HTTP_201_CREATED)
def create_new_live_channel(
    data: PlatformLiveChannelCreate,
    db: Session = Depends(get_db),
):
    return create_live_channel(db, data)


@router.get("/{platform_id}/channels")
def get_platform_live_channels(
    platform_id: UUID,
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    return list_platform_live_channels(
        db,
        platform_id,
        active_only=active_only,
    )