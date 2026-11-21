
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------
# SHARED RESPONSE CONFIGURATION
# ---------------------------------------------------------

class SliderConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------
# SLIDER CURATED TITLES
# ---------------------------------------------------------

class SliderCuratedTitleCreate(BaseModel):
    slider_id: UUID
    tmdb_id: int = Field(gt=0)
    media_type: Literal["movie", "tv"]
    title: str = Field(min_length=1, max_length=255)
    priority: int = Field(default=1, gt=0)
    enabled: bool = True


class SliderCuratedTitleUpdate(BaseModel):
    tmdb_id: int | None = Field(default=None, gt=0)
    media_type: Literal["movie", "tv"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    priority: int | None = Field(default=None, gt=0)
    enabled: bool | None = None


class SliderCuratedTitleResponse(SliderConfigurationResponse):
    id: UUID
    slider_id: UUID
    tmdb_id: int
    media_type: str
    title: str
    priority: int
    enabled: bool
    created_at: datetime


# ---------------------------------------------------------
# SLIDER KEYWORDS
# ---------------------------------------------------------

class SliderKeywordCreate(BaseModel):
    slider_id: UUID
    tmdb_keyword_id: int = Field(gt=0)
    keyword_name: str = Field(min_length=1, max_length=150)
    match_type: Literal["include", "boost"] = "include"
    priority: int = Field(default=1, gt=0)
    enabled: bool = True


class SliderKeywordUpdate(BaseModel):
    tmdb_keyword_id: int | None = Field(default=None, gt=0)
    keyword_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150
    )
    match_type: Literal["include", "boost"] | None = None
    priority: int | None = Field(default=None, gt=0)
    enabled: bool | None = None


class SliderKeywordResponse(SliderConfigurationResponse):
    id: UUID
    slider_id: UUID
    tmdb_keyword_id: int
    keyword_name: str
    match_type: str
    priority: int
    enabled: bool
    created_at: datetime


# ---------------------------------------------------------
# SLIDER COLLECTIONS
# ---------------------------------------------------------

class SliderCollectionCreate(BaseModel):
    slider_id: UUID
    tmdb_collection_id: int = Field(gt=0)
    collection_name: str = Field(min_length=1, max_length=255)
    priority: int = Field(default=1, gt=0)
    enabled: bool = True


class SliderCollectionUpdate(BaseModel):
    tmdb_collection_id: int | None = Field(default=None, gt=0)
    collection_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255
    )
    priority: int | None = Field(default=None, gt=0)
    enabled: bool | None = None


class SliderCollectionResponse(SliderConfigurationResponse):
    id: UUID
    slider_id: UUID
    tmdb_collection_id: int
    collection_name: str
    priority: int
    enabled: bool
    created_at: datetime


# ---------------------------------------------------------
# SLIDER COMPANIES
# ---------------------------------------------------------

class SliderCompanyCreate(BaseModel):
    slider_id: UUID
    tmdb_company_id: int = Field(gt=0)
    company_name: str = Field(min_length=1, max_length=255)
    relation_type: str = Field(default="produced_by", max_length=40)
    priority: int = Field(default=1, gt=0)
    enabled: bool = True


class SliderCompanyUpdate(BaseModel):
    tmdb_company_id: int | None = Field(default=None, gt=0)
    company_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255
    )
    relation_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=40
    )
    priority: int | None = Field(default=None, gt=0)
    enabled: bool | None = None


class SliderCompanyResponse(SliderConfigurationResponse):
    id: UUID
    slider_id: UUID
    tmdb_company_id: int
    company_name: str
    relation_type: str
    priority: int
    enabled: bool
    created_at: datetime


# ---------------------------------------------------------
# SLIDER NETWORKS
# ---------------------------------------------------------

class SliderNetworkCreate(BaseModel):
    slider_id: UUID
    tmdb_network_id: int = Field(gt=0)
    network_name: str = Field(min_length=1, max_length=255)
    priority: int = Field(default=1, gt=0)
    enabled: bool = True


class SliderNetworkUpdate(BaseModel):
    tmdb_network_id: int | None = Field(default=None, gt=0)
    network_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255
    )
    priority: int | None = Field(default=None, gt=0)
    enabled: bool | None = None


class SliderNetworkResponse(SliderConfigurationResponse):
    id: UUID
    slider_id: UUID
    tmdb_network_id: int
    network_name: str
    priority: int
    enabled: bool
    created_at: datetime


# ---------------------------------------------------------
# SLIDER EXCLUDED TITLES
# ---------------------------------------------------------

class SliderExcludedTitleCreate(BaseModel):
    slider_id: UUID
    tmdb_id: int = Field(gt=0)
    media_type: Literal["movie", "tv"]
    title: str = Field(min_length=1, max_length=255)
    reason: str | None = None
    enabled: bool = True


class SliderExcludedTitleUpdate(BaseModel):
    tmdb_id: int | None = Field(default=None, gt=0)
    media_type: Literal["movie", "tv"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    reason: str | None = None
    enabled: bool | None = None


class SliderExcludedTitleResponse(SliderConfigurationResponse):
    id: UUID
    slider_id: UUID
    tmdb_id: int
    media_type: str
    title: str
    reason: str | None
    enabled: bool
    created_at: datetime
