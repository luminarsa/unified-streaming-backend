from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.identity import Profile
from app.models.telemetry import WatchList, WatchProgress
from app.models.platform_config import (
    StreamingPlatform,
    PlatformProfile,
    PlatformProvider,
    PlatformCompany,
    PlatformNetwork,
)
from app.models.commercial import (
    Plan,
    PlanEntitlement,
    Subscription,
)
from app.services.tmdb import TMDBClient, TMDBError


ALGORITHM_VERSION = "recommendations_v1"


# ---------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------

def _validate_media_type(media_type: str):
    if media_type not in ["movie", "tv"]:
        raise HTTPException(
            status_code=400,
            detail="media_type must be either 'movie' or 'tv'.",
        )


def _get_profile(db: Session, profile_id: UUID):
    profile = db.query(Profile).filter(
        Profile.id == profile_id
    ).first()

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found.",
        )

    return profile


def _get_platform(db: Session, platform_slug: str):
    platform = db.query(StreamingPlatform).filter(
        StreamingPlatform.slug == platform_slug,
        StreamingPlatform.is_active == True,
    ).first()

    if not platform:
        raise HTTPException(
            status_code=404,
            detail="Streaming platform not found or inactive.",
        )

    return platform


def _get_platform_region(db: Session, platform_id: UUID) -> str:
    platform_profile = db.query(PlatformProfile).filter(
        PlatformProfile.platform_id == platform_id,
        PlatformProfile.enabled == True,
    ).first()

    if platform_profile and platform_profile.region_code:
        return platform_profile.region_code

    return "ZA"


# ---------------------------------------------------------
# PLATFORM DISCOVERY FILTERS
# ---------------------------------------------------------

def _get_platform_discovery_filter(
    db: Session,
    platform_id: UUID,
    media_type: str,
):
    """
    Builds the strict TMDB discovery filter for a platform.

    TV:
        Uses configured TMDB network IDs.

    Movies:
        Uses configured TMDB production company IDs.

    Fallback:
        If the relevant network/company configuration is empty,
        use the platform's TMDB watch provider ID.
    """

    region = _get_platform_region(db, platform_id)

    params = {
        "sort_by": "popularity.desc",
        "include_adult": "false",
    }

    if media_type == "tv":
        networks = db.query(PlatformNetwork).filter(
            PlatformNetwork.platform_id == platform_id,
            PlatformNetwork.include_in_discovery == True,
        ).all()

        network_ids = [
            str(network.tmdb_network_id)
            for network in networks
            if network.tmdb_network_id
        ]

        if network_ids:
            params["with_networks"] = "|".join(network_ids)
            return params

    else:
        companies = db.query(PlatformCompany).filter(
            PlatformCompany.platform_id == platform_id,
            PlatformCompany.include_in_discovery == True,
        ).all()

        company_ids = [
            str(company.tmdb_company_id)
            for company in companies
            if company.tmdb_company_id
        ]

        if company_ids:
            params["with_companies"] = "|".join(company_ids)
            return params

    # Only use the provider when the relevant media-type
    # network/company configuration is not available.

    providers = db.query(PlatformProvider).filter(
        PlatformProvider.platform_id == platform_id,
        PlatformProvider.provider_kind == "watch_provider",
        PlatformProvider.region_code == region,
    ).order_by(
        PlatformProvider.is_primary.desc()
    ).all()

    provider_ids = [
        str(provider.external_id)
        for provider in providers
        if provider.external_id
    ]

    if not provider_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Platform has no discovery configuration "
                f"for media type '{media_type}' and no "
                f"watch provider fallback configured for "
                f"region '{region}'."
            ),
        )

    params["with_watch_providers"] = "|".join(provider_ids)
    params["watch_region"] = region

    return params


# ---------------------------------------------------------
# TMDB HELPERS
# ---------------------------------------------------------

async def _get_similar_titles(
    tmdb: TMDBClient,
    media_type: str,
    tmdb_id: int,
):
    """
    Fetches similar titles from TMDB.

    Returns a dictionary indexed by TMDB title ID.
    The value represents the title's position in the
    similar results.
    """

    response = await tmdb.get(
        f"/{media_type}/{tmdb_id}/similar",
        params={"page": 1},
    )

    results = response.get("results", [])

    similar_titles = {}

    for position, title in enumerate(results, start=1):
        title_id = title.get("id")

        if title_id:
            similar_titles[title_id] = {
                "position": position,
                "data": title,
            }

    return similar_titles


async def _discover_platform_titles(
    tmdb: TMDBClient,
    media_type: str,
    discovery_params: dict,
    max_pages: int = 5,
):
    """
    Fetches titles matching a platform's discovery filters.

    The results are not recommendations by themselves.
    They are used to restrict recommendations to the
    platform's configured content catalogue.
    """

    discovered_titles = {}

    for page in range(1, max_pages + 1):
        params = {
            **discovery_params,
            "page": page,
        }

        response = await tmdb.discover(
            media_type,
            params,
        )

        for title in response.get("results", []):
            title_id = title.get("id")

            if title_id:
                discovered_titles[title_id] = title

        total_pages = response.get("total_pages", 1)

        if page >= total_pages:
            break

    return discovered_titles


# ---------------------------------------------------------
# RECOMMENDATION SCORING
# ---------------------------------------------------------

def _get_preferred_genre_ids(profile: Profile) -> set[int]:
    """
    Reads optional genre preferences from Profile.preferences.

    Supported preference keys:
        favorite_genre_ids
        preferred_genre_ids
        genre_ids
    """

    preferences = profile.preferences or {}

    if not isinstance(preferences, dict):
        return set()

    genre_ids = (
        preferences.get("favorite_genre_ids")
        or preferences.get("preferred_genre_ids")
        or preferences.get("genre_ids")
        or []
    )

    result = set()

    for genre_id in genre_ids:
        try:
            result.add(int(genre_id))
        except (ValueError, TypeError):
            continue

    return result


def _calculate_recommendation_score(
    title: dict,
    similar_position: int,
    preferred_genres: set[int],
):
    """
    Calculates a ranking score.

    Signals:
        1. Position in TMDB similar results.
        2. Preferred genre overlap.
        3. TMDB vote average.
        4. TMDB popularity.
    """

    # Earlier TMDB similar results receive a higher score.
    similarity_score = 1 / similar_position

    # Compare candidate genres with profile preferences.
    candidate_genres = set(title.get("genre_ids", []))

    genre_score = 0

    if preferred_genres and candidate_genres:
        overlap = candidate_genres.intersection(
            preferred_genres
        )

        genre_score = len(overlap) / len(preferred_genres)

    vote_average = float(title.get("vote_average") or 0)

    rating_score = min(vote_average / 10, 1)

    popularity = float(title.get("popularity") or 0)

    popularity_score = min(popularity / 1000, 1)

    final_score = (
        (similarity_score * 0.60)
        + (genre_score * 0.25)
        + (rating_score * 0.10)
        + (popularity_score * 0.05)
    )

    return round(final_score, 8)


def _prepare_recommendation(
    title: dict,
    media_type: str,
    score: float,
    reason_code: str,
    platforms: list[str],
):
    """
    Standardises the TMDB title and recommendation data
    for the API response.
    """

    result = dict(title)

    result["media_type"] = media_type
    result["score"] = score
    result["reason_code"] = reason_code
    result["platforms"] = platforms

    return result


# ---------------------------------------------------------
# PLATFORM-SPECIFIC SIMILAR RECOMMENDATIONS
# ---------------------------------------------------------

async def get_similar_recommendations(
    db: Session,
    profile_id: UUID,
    platform_slug: str,
    media_type: str,
    tmdb_id: int,
    limit: int = 20,
):
    """
    Returns similar titles associated with one platform.

    The candidate must:
        1. Appear in TMDB similar-title results.
        2. Appear in the platform-filtered TMDB discovery results.

    The selected profile's genre preferences are used
    to influence the final ranking.
    """

    _validate_media_type(media_type)

    if tmdb_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="tmdb_id must be greater than zero.",
        )

    limit = max(1, min(limit, 50))

    profile = _get_profile(db, profile_id)

    platform = _get_platform(db, platform_slug)

    if media_type == "movie" and not platform.supports_movies:
        raise HTTPException(
            status_code=400,
            detail="This platform does not support movies.",
        )

    if media_type == "tv" and not platform.supports_tv_shows:
        raise HTTPException(
            status_code=400,
            detail="This platform does not support TV shows.",
        )

    tmdb = TMDBClient()

    try:
        # 1. Get titles similar to the current title.
        similar_titles = await _get_similar_titles(
            tmdb,
            media_type,
            tmdb_id,
        )

        if not similar_titles:
            return {
                "platform_slug": platform.slug,
                "media_type": media_type,
                "tmdb_id": tmdb_id,
                "total_results": 0,
                "results": [],
            }

        # 2. Get the platform's strict discovery filter.
        discovery_params = _get_platform_discovery_filter(
            db,
            platform.id,
            media_type,
        )

        # 3. Fetch titles associated with that platform.
        platform_titles = await _discover_platform_titles(
            tmdb,
            media_type,
            discovery_params,
        )

        # 4. Intersect both result sets.
        # A title must be in BOTH collections.
        preferred_genres = _get_preferred_genre_ids(profile)

        recommendations = []

        for title_id, title in platform_titles.items():
            if title_id not in similar_titles:
                continue

            if title_id == tmdb_id:
                continue

            similarity_position = similar_titles[
                title_id
            ]["position"]

            score = _calculate_recommendation_score(
                title,
                similarity_position,
                preferred_genres,
            )

            recommendations.append(
                _prepare_recommendation(
                    title=title,
                    media_type=media_type,
                    score=score,
                    reason_code="SIMILAR_TO_CURRENT_TITLE",
                    platforms=[platform.slug],
                )
            )

        recommendations.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        recommendations = recommendations[:limit]

        return {
            "platform_slug": platform.slug,
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "total_results": len(recommendations),
            "results": recommendations,
        }

    except TMDBError:
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve recommendations from TMDB.",
        )


# ---------------------------------------------------------
# ACCOUNT SUBSCRIPTION AND PLATFORM ENTITLEMENTS
# ---------------------------------------------------------

def _get_entitled_platforms(
    db: Session,
    account_id: UUID,
):
    """
    Finds the account's currently active subscription
    and returns the platforms included in its plan.
    """

    now = datetime.now(timezone.utc)

    subscription = db.query(Subscription).filter(
        Subscription.account_id == account_id,
        Subscription.status == "active",
        (
            (Subscription.current_period_start == None)
            | (Subscription.current_period_start <= now)
        ),
        (
            (Subscription.current_period_end == None)
            | (Subscription.current_period_end > now)
        ),
    ).order_by(
        Subscription.created_at.desc()
    ).first()

    if not subscription:
        raise HTTPException(
            status_code=403,
            detail="No active subscription found for this account.",
        )

    plan = db.query(Plan).filter(
        Plan.id == subscription.plan_id,
        Plan.is_active == True,
    ).first()

    if not plan:
        raise HTTPException(
            status_code=403,
            detail="The account's subscription plan is inactive.",
        )

    platforms = db.query(StreamingPlatform).join(
        PlanEntitlement,
        PlanEntitlement.platform_id == StreamingPlatform.id,
    ).filter(
        PlanEntitlement.plan_id == plan.id,
        StreamingPlatform.is_active == True,
    ).all()

    return platforms


# ---------------------------------------------------------
# PROFILE VIEWING HISTORY
# ---------------------------------------------------------

def _get_profile_seeds(
    db: Session,
    profile_id: UUID,
    limit: int = 10,
):
    """
    Gets the profile's recent viewing history and watchlist.

    These titles are used as seeds for personalised
    recommendations.
    """

    progress_records = db.query(WatchProgress).filter(
        WatchProgress.profile_id == profile_id,
    ).order_by(
        WatchProgress.last_watched_at.desc()
    ).limit(limit).all()

    watchlist_records = db.query(WatchList).filter(
        WatchList.profile_id == profile_id,
    ).order_by(
        WatchList.created_at.desc()
    ).limit(limit).all()

    seeds = []
    seen = set()

    # Recent viewing activity.
    for record in progress_records:
        key = (record.tmdb_id, record.media_type)

        if key not in seen:
            seeds.append({
                "tmdb_id": record.tmdb_id,
                "media_type": record.media_type,
            })
            seen.add(key)

    # Watchlist activity.
    for record in watchlist_records:
        key = (record.tmdb_id, record.media_type)

        if key not in seen:
            seeds.append({
                "tmdb_id": record.tmdb_id,
                "media_type": record.media_type,
            })
            seen.add(key)

    return seeds


def _get_excluded_titles(
    db: Session,
    profile_id: UUID,
):
    """
    Titles already watched, in progress, or on the
    profile's watchlist are excluded from recommendations.
    """

    excluded = set()

    progress_records = db.query(WatchProgress).filter(
        WatchProgress.profile_id == profile_id,
    ).all()

    for record in progress_records:
        excluded.add(
            (record.tmdb_id, record.media_type)
        )

    watchlist_records = db.query(WatchList).filter(
        WatchList.profile_id == profile_id,
    ).all()

    for record in watchlist_records:
        excluded.add(
            (record.tmdb_id, record.media_type)
        )

    return excluded


# ---------------------------------------------------------
# ACCOUNT-WIDE PERSONALIZED RECOMMENDATIONS
# ---------------------------------------------------------

async def get_personalized_recommendations(
    db: Session,
    profile_id: UUID,
    limit: int = 30,
):
    """
    Generates recommendations across all platforms
    included in the account's active subscription.

    Recommendations are based on the selected profile's
    viewing history, watchlist and genre preferences.
    """

    limit = max(1, min(limit, 50))

    profile = _get_profile(db, profile_id)

    # The account ID comes from the selected profile.
    # The frontend never supplies an account ID here.
    entitled_platforms = _get_entitled_platforms(
        db,
        profile.account_id,
    )

    if not entitled_platforms:
        return {
            "profile_id": str(profile.id),
            "algorithm_version": ALGORITHM_VERSION,
            "total_results": 0,
            "results": [],
        }

    seeds = _get_profile_seeds(
        db,
        profile.id,
    )

    excluded_titles = _get_excluded_titles(
        db,
        profile.id,
    )

    preferred_genres = _get_preferred_genre_ids(profile)

    tmdb = TMDBClient()

    # Build similar-title lookup maps for each media type.
    similar_by_media_type = {
        "movie": {},
        "tv": {},
    }

    try:
        # Fetch similar titles for the profile's recent seeds.
        # This is done once per seed, not once per platform.
        for seed in seeds:
            media_type = seed["media_type"]
            tmdb_id = seed["tmdb_id"]

            if media_type not in similar_by_media_type:
                continue

            similar_titles = await _get_similar_titles(
                tmdb,
                media_type,
                tmdb_id,
            )

            for title_id, information in similar_titles.items():
                current = similar_by_media_type[media_type].get(
                    title_id
                )

                # Keep the best similarity position across seeds.
                if (
                    current is None
                    or information["position"] < current["position"]
                ):
                    similar_by_media_type[media_type][title_id] = (
                        information
                    )

        # If the profile has no viewing history, its saved
        # genre preferences can provide a cold-start signal.
        recommendations_by_title = {}

        for platform in entitled_platforms:
            for media_type in ["movie", "tv"]:

                if media_type == "movie" and not platform.supports_movies:
                    continue

                if media_type == "tv" and not platform.supports_tv_shows:
                    continue

                try:
                    discovery_params = _get_platform_discovery_filter(
                        db,
                        platform.id,
                        media_type,
                    )
                except HTTPException as exc:
                    if exc.status_code == 400:
                        continue
                    raise

                if preferred_genres and not seeds:
                    discovery_params["with_genres"] = "|".join(
                        str(genre_id)
                        for genre_id in sorted(preferred_genres)
                    )

                platform_titles = await _discover_platform_titles(
                    tmdb,
                    media_type,
                    discovery_params,
                    max_pages=3,
                )

                similar_titles = similar_by_media_type[media_type]

                for title_id, title in platform_titles.items():

                    key = (title_id, media_type)

                    # Do not recommend something the profile
                    # has already watched or saved.
                    if key in excluded_titles:
                        continue

                    # With viewing history, candidates must be
                    # similar to at least one seed.
                    if seeds and title_id not in similar_titles:
                        continue

                    if seeds:
                        similarity_position = similar_titles[
                            title_id
                        ]["position"]
                    else:
                        similarity_position = 2

                    score = _calculate_recommendation_score(
                        title,
                        similarity_position,
                        preferred_genres,
                    )

                    if key not in recommendations_by_title:
                        recommendations_by_title[key] = (
                            _prepare_recommendation(
                                title=title,
                                media_type=media_type,
                                score=score,
                                reason_code=(
                                    "BASED_ON_PROFILE_ACTIVITY"
                                    if seeds
                                    else "BASED_ON_PROFILE_PREFERENCES"
                                ),
                                platforms=[platform.slug],
                            )
                        )

                    else:
                        existing = recommendations_by_title[key]

                        # Retain the strongest score when the
                        # same title appears on multiple platforms.
                        existing["score"] = max(
                            existing["score"],
                            score,
                        )

                        if platform.slug not in existing["platforms"]:
                            existing["platforms"].append(
                                platform.slug
                            )

        recommendations = list(
            recommendations_by_title.values()
        )

        recommendations.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        recommendations = recommendations[:limit]

        return {
            "profile_id": str(profile.id),
            "algorithm_version": ALGORITHM_VERSION,
            "total_results": len(recommendations),
            "results": recommendations,
        }

    except TMDBError:
        raise HTTPException(
            status_code=502,
            detail="Unable to generate personalized recommendations from TMDB.",
        )