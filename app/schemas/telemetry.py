
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


MediaType = Literal["movie", "tv"]

EventType = Literal[
    "play",
    "pause",
    "seeked",
    "timeupdate",
    "ended",
]


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
