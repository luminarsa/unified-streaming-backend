
from typing import Literal

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.v1.dependencies import get_active_profile

from app.models.identity import Profile

from app.schemas.recommendations import (
    SimilarRecommendationsResponse,
    PersonalizedRecommendationsResponse,
)

from app.services.recommendations import (
    get_similar_recommendations,
    get_personalized_recommendations,
)


router = APIRouter(
    prefix="/recommendations",
    tags=["Recommendations"],
)


# ---------------------------------------------------------
# PLATFORM-SPECIFIC SIMILAR RECOMMENDATIONS
# ---------------------------------------------------------

@router.get(
    "/similar",
    response_model=SimilarRecommendationsResponse,
)
async def similar_recommendations(
    platform_slug: str = Query(
        ...,
        description="Platform slug, for example netflix or disney-plus.",
    ),
    media_type: Literal["movie", "tv"] = Query(
        ...,
        description="Content type: movie or tv.",
    ),
    tmdb_id: int = Query(
        ...,
        gt=0,
        description="TMDB ID of the movie or TV show being viewed.",
    ),
    limit: int = Query(
        20,
        ge=1,
        le=50,
        description="Maximum number of recommendations.",
    ),
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    """
    Returns similar titles associated with a specific platform.

    The selected profile is obtained from the authentication
    dependency. The frontend cannot choose another profile.
    """

    return await get_similar_recommendations(
        db=db,
        profile_id=profile.id,
        platform_slug=platform_slug,
        media_type=media_type,
        tmdb_id=tmdb_id,
        limit=limit,
    )


# ---------------------------------------------------------
# ACCOUNT-WIDE PERSONALIZED RECOMMENDATIONS
# ---------------------------------------------------------

@router.get(
    "",
    response_model=PersonalizedRecommendationsResponse,
)
async def personalized_recommendations(
    limit: int = Query(
        30,
        ge=1,
        le=50,
        description="Maximum number of recommendations.",
    ),
    profile: Profile = Depends(get_active_profile),
    db: Session = Depends(get_db),
):
    """
    Returns personalized recommendations across platforms
    included in the account's active subscription.

    Recommendations are based on the selected profile's
    viewing history, watchlist and preferences.
    """

    return await get_personalized_recommendations(
        db=db,
        profile_id=profile.id,
        limit=limit,
    )

    print("SIMILAR TMDB RESULTS:", len(similar_titles))
    print("PLATFORM DISCOVERY RESULTS:", len(platform_titles))

    print(
        "SIMILAR TMDB IDS:",
        list(similar_titles.keys())[:20]
    )

    print(
        "PLATFORM DISCOVERY IDS:",
        list(platform_titles.keys())[:20]
    )

    print(
        "INTERSECTION:",
        set(similar_titles.keys()).intersection(
            platform_titles.keys()
        )
    )