
from pydantic import BaseModel
from typing import List


class WatchProviderEntitlement(BaseModel):
    tmdb_id: int
    provider_kind: str
    region_code: str | None = None
    is_primary: bool


class NetworkEntitlement(BaseModel):
    tmdb_id: int
    name: str


class CompanyEntitlement(BaseModel):
    tmdb_id: int
    name: str
    relation_type: str


class ProfileSearchRestrictions(BaseModel):
    profile_id: str
    profile_type: str
    is_kids_profile: bool
    allow_adult_content: bool
    content_rating_policy: str


class PlatformSearchEntitlements(BaseModel):
    platform_id: str
    platform_name: str
    platform_slug: str

    region_code: str
    language: str

    supports_movies: bool
    supports_tv_shows: bool

    allowed_content_types: List[str]

    profile: ProfileSearchRestrictions

    search_entitlements: dict

    watch_providers: List[WatchProviderEntitlement]
    networks: List[NetworkEntitlement]
    production_companies: List[CompanyEntitlement]
