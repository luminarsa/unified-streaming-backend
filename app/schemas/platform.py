
from typing import Any, Literal

from pydantic import BaseModel, Field
from uuid import UUID


# ---------------------------------------------------------
# STREAMING PLATFORM
# ---------------------------------------------------------

class PlatformCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=120)
    description: str | None = None
    logo_url: str | None = None
    icon: str | None = None

    supports_movies: bool = True
    supports_tv_shows: bool = True
    supports_live_tv: bool = False

    is_active: bool = True
    display_order: int = 0


class PlatformUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    logo_url: str | None = None

    supports_movies: bool | None = None
    supports_tv_shows: bool | None = None
    supports_live_tv: bool | None = None

    is_active: bool | None = None
    display_order: int | None = None


# ---------------------------------------------------------
# PLATFORM PROFILE
# ---------------------------------------------------------

class PlatformProfileCreate(BaseModel):
    platform_id: UUID
    config_version: int = Field(default=1, ge=1)
    region_code: str = Field(default="ZA", min_length=2, max_length=2)
    language: str = Field(default="en-US", max_length=10)
    default_row_count: int = Field(default=12, gt=0)
    enabled: bool = True
    fallback_policy: dict[str, Any] = Field(default_factory=dict)


class PlatformProfileUpdate(BaseModel):
    config_version: int | None = Field(default=None, ge=1)
    region_code: str | None = Field(default=None, min_length=2, max_length=2)
    language: str | None = Field(default=None, max_length=10)
    default_row_count: int | None = Field(default=None, gt=0)
    enabled: bool | None = None
    fallback_policy: dict[str, Any] | None = None


# ---------------------------------------------------------
# TMDB WATCH PROVIDER
# ---------------------------------------------------------

class PlatformProviderCreate(BaseModel):
    platform_id: UUID
    provider_kind: str = Field(min_length=1, max_length=20)
    external_id: int = Field(gt=0)
    region_code: str | None = Field(default=None, min_length=2, max_length=2)
    is_primary: bool = False
    source: str = Field(default="manual", max_length=40)


# ---------------------------------------------------------
# TMDB PRODUCTION COMPANY
# ---------------------------------------------------------

class PlatformCompanyCreate(BaseModel):
    platform_id: UUID
    tmdb_company_id: int = Field(gt=0)
    relation_type: str = Field(default="produced_by", max_length=40)
    include_in_discovery: bool = True
    confidence: str = Field(default="verified", max_length=20)


# ---------------------------------------------------------
# TMDB TV NETWORK
# ---------------------------------------------------------

class PlatformNetworkCreate(BaseModel):
    platform_id: UUID
    tmdb_network_id: int = Field(gt=0)
    include_in_discovery: bool = True


# ---------------------------------------------------------
# HOME PAGE SLIDER
# ---------------------------------------------------------

class SliderCreate(BaseModel):
    platform_id: UUID
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)

    # The service will interpret this strategy when fetching content.
    strategy: str = Field(min_length=1, max_length=40)

    media_scope: Literal["mixed", "movies", "tv_shows"] = "mixed"

    genre_ids: list[int] = Field(default_factory=list)
    query_overrides: dict[str, Any] = Field(default_factory=dict)

    display_order: int = 0
    page_size: int = Field(default=25, gt=0)
    enabled: bool = True


class SliderUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=80)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    strategy: str | None = Field(default=None, min_length=1, max_length=40)

    media_scope: Literal["mixed", "movies", "tv_shows"] | None = None

    genre_ids: list[int] | None = None
    query_overrides: dict[str, Any] | None = None

    display_order: int | None = None
    page_size: int | None = Field(default=None, gt=0)
    enabled: bool | None = None


# ---------------------------------------------------------
# PLATFORM NAVIGATION
# ---------------------------------------------------------

class PlatformNavigationCreate(BaseModel):
    platform_id: UUID
    key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    route: str = Field(min_length=1, max_length=160)

    display_order: int = 0
    enabled: bool = True
    requires_feature: Literal["always", "live_tv"] = "always"


# ---------------------------------------------------------
# LIVE TV CHANNEL
# ---------------------------------------------------------

class PlatformLiveChannelCreate(BaseModel):
    platform_id: UUID | None
    channel_key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)

    logo_url: str | None = None
    stream_url: str | None = None
    channel_number: int | None = Field(default=None, gt=0)

    display_order: int = 0
    is_news_channel: bool = False
    is_active: bool = True
    metadata_json: dict[str, Any] = Field(default_factory=dict)
