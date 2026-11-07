
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, model_validator, ConfigDict, Field


MediaType = Literal["movie", "tv"]

EventType = Literal[
    "play",
    "pause",
    "seeked",
    "timeupdate",
    "ended",
]

class WatchListCreate(BaseModel):
    platform_id: UUID
    tmdb_id: int = Field(gt=0)
    media_type: MediaType


class WatchListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: UUID
    platform_id: UUID
    tmdb_id: int
    media_type: MediaType

    title: str
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    release_date: str | None = None
    genre_ids: list[int] = Field(default_factory=list)
    original_language: str | None = None
    vote_average: Decimal | None = None

    tmdb_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WatchListPlatformGroup(BaseModel):
    platform_id: UUID
    platform_name: str
    platform_slug: str
    items: list[WatchListItemResponse] = Field(default_factory=list)


class WatchListCheckResponse(BaseModel):
    saved: bool
    item_id: UUID | None = None


class WatchListDeleteResponse(BaseModel):
    message: str
    item_id: UUID

class ViewingSessionCreate(BaseModel):
    client_session_key: UUID
    tmdb_id: int = Field(gt=0)
    media_type: MediaType
    platform_id: UUID | None = None
    player_provider: str = "vidrock"
    tracking_mode: str = "player_events"


class ViewingSessionResponse(BaseModel):
    id: UUID
    tmdb_id: int
    media_type: str
    status: str
    started_at: datetime

    model_config = {"from_attributes": True}


class ViewingEventCreate(BaseModel):
    event_key: UUID
    event_type: EventType
    position_seconds: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    season_number: int | None = Field(default=None, gt=0)
    episode_number: int | None = Field(default=None, gt=0)
    client_timestamp: datetime | None = None
    visible: bool | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_episode_numbers(self):
        if (self.season_number is None) != (
            self.episode_number is None
        ):
            raise ValueError(
                "season_number and episode_number must be "
                "provided together."
            )
        return self


class WatchProgressResponse(BaseModel):
    tmdb_id: int
    media_type: str
    season_number: int | None
    episode_number: int | None
    position_seconds: float | None
    duration_seconds: float | None
    progress_ratio: float | None
    progress_source: str
    status: str
    last_watched_at: datetime

    model_config = {"from_attributes": True}
