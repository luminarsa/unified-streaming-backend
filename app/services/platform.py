
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.platform_config import (
    StreamingPlatform,
    PlatformProfile,
    PlatformProvider,
    PlatformCompany,
    PlatformNetwork,
    SliderDefinition,
    PlatformNavigationItem,
    PlatformLiveChannel,
)


# ---------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------

def _commit(db: Session, message: str = "A record with these details already exists."):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=message)


def _require_platform(db: Session, platform_id: UUID):
    platform = db.get(StreamingPlatform, platform_id)

    if platform is None:
        raise HTTPException(status_code=404, detail="Platform not found.")

    return platform


def _platform_data(platform: StreamingPlatform) -> dict:
    return {
        "id": str(platform.id),
        "name": platform.name,
        "slug": platform.slug,
        "description": platform.description,
        "logo_url": platform.logo_url,
        "supports_movies": platform.supports_movies,
        "supports_tv_shows": platform.supports_tv_shows,
        "supports_live_tv": platform.supports_live_tv,
        "is_active": platform.is_active,
        "display_order": platform.display_order,
        "created_at": platform.created_at.isoformat() if platform.created_at else None,
        "updated_at": platform.updated_at.isoformat() if platform.updated_at else None,
    }


def _profile_data(profile: PlatformProfile) -> dict:
    return {
        "id": str(profile.id),
        "platform_id": str(profile.platform_id),
        "config_version": profile.config_version,
        "region_code": profile.region_code,
        "language": profile.language,
        "default_row_count": profile.default_row_count,
        "enabled": profile.enabled,
        "fallback_policy": profile.fallback_policy,
    }


def _provider_data(provider: PlatformProvider) -> dict:
    return {
        "id": str(provider.id),
        "platform_id": str(provider.platform_id),
        "provider_kind": provider.provider_kind,
        "external_id": provider.external_id,
        "region_code": provider.region_code,
        "is_primary": provider.is_primary,
        "source": provider.source,
    }


def _company_data(company: PlatformCompany) -> dict:
    return {
        "id": str(company.id),
        "platform_id": str(company.platform_id),
        "tmdb_company_id": company.tmdb_company_id,
        "relation_type": company.relation_type,
        "include_in_discovery": company.include_in_discovery,
        "confidence": company.confidence,
    }


def _network_data(network: PlatformNetwork) -> dict:
    return {
        "id": str(network.id),
        "platform_id": str(network.platform_id),
        "tmdb_network_id": network.tmdb_network_id,
        "include_in_discovery": network.include_in_discovery,
    }


def _slider_data(slider: SliderDefinition) -> dict:
    return {
        "id": str(slider.id),
        "platform_id": str(slider.platform_id),
        "key": slider.key,
        "title": slider.title,
        "strategy": slider.strategy,
        "media_scope": slider.media_scope,
        "genre_ids": slider.genre_ids,
        "query_overrides": slider.query_overrides,
        "display_order": slider.display_order,
        "page_size": slider.page_size,
        "enabled": slider.enabled,
    }


def _navigation_data(item: PlatformNavigationItem) -> dict:
    return {
        "id": str(item.id),
        "platform_id": str(item.platform_id),
        "key": item.key,
        "label": item.label,
        "route": item.route,
        "display_order": item.display_order,
        "enabled": item.enabled,
        "requires_feature": item.requires_feature,
    }


def _channel_data(channel: PlatformLiveChannel) -> dict:
    return {
        "id": str(channel.id),
        "platform_id": str(channel.platform_id),
        "channel_key": channel.channel_key,
        "name": channel.name,
        "logo_url": channel.logo_url,
        "stream_url": channel.stream_url,
        "channel_number": channel.channel_number,
        "display_order": channel.display_order,
        "is_active": channel.is_active,
        "metadata_json": channel.metadata_json,
    }


# ---------------------------------------------------------
# STREAMING PLATFORM SERVICES
# ---------------------------------------------------------

def create_platform(db: Session, data) -> dict:
    platform = StreamingPlatform(**data.model_dump())

    db.add(platform)
    _commit(db, "A platform with this name or slug already exists.")
    db.refresh(platform)

    return _platform_data(platform)


def list_platforms(db: Session, active_only: bool = False) -> list:
    query = select(StreamingPlatform)

    if active_only:
        query = query.where(StreamingPlatform.is_active.is_(True))

    query = query.order_by(
        StreamingPlatform.display_order,
        StreamingPlatform.name,
    )

    platforms = db.scalars(query).all()

    return [_platform_data(platform) for platform in platforms]


def get_platform(db: Session, platform_id: UUID) -> dict:
    platform = _require_platform(db, platform_id)
    return _platform_data(platform)


def update_platform(db: Session, platform_id: UUID, data) -> dict:
    platform = _require_platform(db, platform_id)

    changes = data.model_dump(exclude_unset=True)

    for field, value in changes.items():
        setattr(platform, field, value)

    _commit(db, "A platform with this name or slug already exists.")
    db.refresh(platform)

    return _platform_data(platform)


def delete_platform(db: Session, platform_id: UUID) -> dict:
    platform = _require_platform(db, platform_id)

    db.delete(platform)
    db.commit()

    return {
        "message": "Platform deleted successfully.",
        "platform_id": str(platform_id),
    }



# ---------------------------------------------------------
# PLATFORM PROFILE SERVICES
# ---------------------------------------------------------

def create_platform_profile(db: Session, data) -> dict:
    _require_platform(db, data.platform_id)

    profile = PlatformProfile(**data.model_dump())
    db.add(profile)

    _commit(db, "A profile configuration already exists for this platform.")
    db.refresh(profile)

    return _profile_data(profile)


def get_platform_profile(db: Session, platform_id: UUID) -> dict:
    profile = db.scalar(
        select(PlatformProfile).where(
            PlatformProfile.platform_id == platform_id
        )
    )

    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="Platform profile configuration not found.",
        )

    return _profile_data(profile)


def update_platform_profile(db: Session, platform_id: UUID, data) -> dict:
    profile = db.scalar(
        select(PlatformProfile).where(
            PlatformProfile.platform_id == platform_id
        )
    )

    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="Platform profile configuration not found.",
        )

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    _commit(db, "Unable to update platform profile configuration.")
    db.refresh(profile)

    return _profile_data(profile)


# ---------------------------------------------------------
# WATCH PROVIDER SERVICES
# ---------------------------------------------------------

def create_platform_provider(db: Session, data) -> dict:
    _require_platform(db, data.platform_id)

    provider = PlatformProvider(**data.model_dump())

    # Keep one primary provider per platform, provider type and region.
    if provider.is_primary:
        query = select(PlatformProvider).where(
            PlatformProvider.platform_id == provider.platform_id,
            PlatformProvider.provider_kind == provider.provider_kind,
        )

        if provider.region_code is None:
            query = query.where(PlatformProvider.region_code.is_(None))
        else:
            query = query.where(
                PlatformProvider.region_code == provider.region_code
            )

        existing = db.scalars(query).all()

        for item in existing:
            item.is_primary = False

    db.add(provider)
    _commit(db, "This provider mapping already exists.")
    db.refresh(provider)

    return _provider_data(provider)


def list_platform_providers(db: Session, platform_id: UUID) -> list:
    _require_platform(db, platform_id)

    providers = db.scalars(
        select(PlatformProvider)
        .where(PlatformProvider.platform_id == platform_id)
        .order_by(PlatformProvider.provider_kind, PlatformProvider.external_id)
    ).all()

    return [_provider_data(item) for item in providers]


# ---------------------------------------------------------
# PRODUCTION COMPANY SERVICES
# ---------------------------------------------------------

def create_platform_company(db: Session, data) -> dict:
    _require_platform(db, data.platform_id)

    company = PlatformCompany(**data.model_dump())
    db.add(company)

    _commit(db, "This company mapping already exists.")
    db.refresh(company)

    return _company_data(company)


def list_platform_companies(db: Session, platform_id: UUID) -> list:
    _require_platform(db, platform_id)

    companies = db.scalars(
        select(PlatformCompany)
        .where(PlatformCompany.platform_id == platform_id)
        .order_by(PlatformCompany.tmdb_company_id)
    ).all()

    return [_company_data(item) for item in companies]


# ---------------------------------------------------------
# TV NETWORK SERVICES
# ---------------------------------------------------------

def create_platform_network(db: Session, data) -> dict:
    _require_platform(db, data.platform_id)

    network = PlatformNetwork(**data.model_dump())
    db.add(network)

    _commit(db, "This network mapping already exists.")
    db.refresh(network)

    return _network_data(network)


def list_platform_networks(db: Session, platform_id: UUID) -> list:
    _require_platform(db, platform_id)

    networks = db.scalars(
        select(PlatformNetwork)
        .where(PlatformNetwork.platform_id == platform_id)
        .order_by(PlatformNetwork.tmdb_network_id)
    ).all()

    return [_network_data(item) for item in networks]


# ---------------------------------------------------------
# HOME PAGE SLIDER SERVICES
# ---------------------------------------------------------

def create_slider(db: Session, data) -> dict:
    _require_platform(db, data.platform_id)

    slider = SliderDefinition(**data.model_dump())
    db.add(slider)

    _commit(db, "A slider with this key already exists on this platform.")
    db.refresh(slider)

    return _slider_data(slider)


def list_platform_sliders(
    db: Session,
    platform_id: UUID,
    enabled_only: bool = False,
) -> list:
    _require_platform(db, platform_id)

    query = select(SliderDefinition).where(
        SliderDefinition.platform_id == platform_id
    )

    if enabled_only:
        query = query.where(SliderDefinition.enabled.is_(True))

    sliders = db.scalars(
        query.order_by(
            SliderDefinition.display_order,
            SliderDefinition.id,
        )
    ).all()

    return [_slider_data(item) for item in sliders]


def update_slider(db: Session, slider_id: UUID, data) -> dict:
    slider = db.get(SliderDefinition, slider_id)

    if slider is None:
        raise HTTPException(status_code=404, detail="Slider not found.")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(slider, field, value)

    _commit(db, "A slider with this key already exists on this platform.")
    db.refresh(slider)

    return _slider_data(slider)


# ---------------------------------------------------------
# PLATFORM NAVIGATION SERVICES
# ---------------------------------------------------------

def create_navigation_item(db: Session, data) -> dict:
    platform = _require_platform(db, data.platform_id)

    if (
        data.requires_feature == "live_tv"
        and not platform.supports_live_tv
    ):
        raise HTTPException(
            status_code=400,
            detail="This platform does not support Live TV.",
        )

    item = PlatformNavigationItem(**data.model_dump())
    db.add(item)

    _commit(db, "This navigation key already exists on this platform.")
    db.refresh(item)

    return _navigation_data(item)


def list_platform_navigation(
    db: Session,
    platform_id: UUID,
    enabled_only: bool = False,
) -> list:
    _require_platform(db, platform_id)

    query = select(PlatformNavigationItem).where(
        PlatformNavigationItem.platform_id == platform_id
    )

    if enabled_only:
        query = query.where(PlatformNavigationItem.enabled.is_(True))

    items = db.scalars(
        query.order_by(
            PlatformNavigationItem.display_order,
            PlatformNavigationItem.id,
        )
    ).all()

    return [_navigation_data(item) for item in items]


# ---------------------------------------------------------
# LIVE TV CHANNEL SERVICES
# ---------------------------------------------------------

def create_live_channel(db: Session, data) -> dict:
    platform = _require_platform(db, data.platform_id)

    if not platform.supports_live_tv:
        raise HTTPException(
            status_code=400,
            detail="Live TV is not enabled for this platform.",
        )

    channel = PlatformLiveChannel(**data.model_dump())
    db.add(channel)

    _commit(db, "This channel key already exists on this platform.")
    db.refresh(channel)

    return _channel_data(channel)


def list_platform_live_channels(
    db: Session,
    platform_id: UUID,
    active_only: bool = False,
) -> list:
    platform = _require_platform(db, platform_id)

    if not platform.supports_live_tv:
        return []

    query = select(PlatformLiveChannel).where(
        PlatformLiveChannel.platform_id == platform_id
    )

    if active_only:
        query = query.where(PlatformLiveChannel.is_active.is_(True))

    channels = db.scalars(
        query.order_by(
            PlatformLiveChannel.display_order,
            PlatformLiveChannel.channel_number,
            PlatformLiveChannel.name,
        )
    ).all()

    return [_channel_data(item) for item in channels]
