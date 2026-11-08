from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class RecommendationTitle(BaseModel):
    """
    Represents a recommended movie or TV show.

    Fields are based on TMDB responses, with additional
    recommendation information added by our backend.
    """

    model_config = ConfigDict(extra="allow")

    id: int

    media_type: str

    title: Optional[str] = None
    name: Optional[str] = None

    overview: Optional[str] = None

    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None

    release_date: Optional[str] = None
    first_air_date: Optional[str] = None

    genre_ids: list[int] = Field(default_factory=list)

    original_language: Optional[str] = None

    vote_average: Optional[float] = None
    vote_count: Optional[int] = None

    popularity: Optional[float] = None

    # Recommendation engine information.
    score: Optional[float] = None
    reason_code: Optional[str] = None

    # Platforms on which this title is associated/available
    # according to our platform configuration.
    platforms: list[str] = Field(default_factory=list)


class SimilarRecommendationsResponse(BaseModel):
    """Response for platform-specific similar recommendations."""

    platform_slug: str
    media_type: str
    tmdb_id: int

    total_results: int

    results: list[RecommendationTitle] = Field(
        default_factory=list
    )


class PersonalizedRecommendationsResponse(BaseModel):
    """Response for account-wide personalized recommendations."""

    profile_id: str

    algorithm_version: str

    total_results: int

    results: list[RecommendationTitle] = Field(
        default_factory=list
    )


class ProfileContentSignalResponse(BaseModel):
    """Represents a learned preference signal for a profile."""

    tmdb_id: int
    media_type: str
    signal_type: str

    signal_value: float
    confidence: float
    evidence_count: int

    class Config:
        from_attributes = True