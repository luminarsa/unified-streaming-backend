from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from datetime import datetime, timedelta, timezone
from datetime import date
from app.models.commercial import (
    Plan,
    PlanEntitlement,
    PlanFeature,
    Subscription,
)
from app.models.platform_config import (
    StreamingPlatform,
    PlatformProfile,
    PlatformProvider,
    PlatformCompany,
    PlatformNetwork,
    PlatformLiveChannel,
    SliderDefinition,
)
from app.models.identity import Profile
from app.models.telemetry import ViewingSession, WatchProgress
from app.services.tmdb_client import TMDBClient
import random
import json
import hashlib
import logging
from app.services.cache_service import get_cache, set_cache

logger = logging.getLogger(__name__)

IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

# Conservative initial allowlist for child profiles.
# You can override this in Profile.preferences using
# {"allowed_certifications": ["A", "PG", "G", "TV-Y"]}.
DEFAULT_CHILD_CERTIFICATIONS = {
    "A", "G", "PG", "U", "0", "6", "7",
    "7-9PG", "TV-Y", "TV-Y7", "TV-G", "TV-PG",
}

# Only allow harmless discovery overrides from slider configuration.
ALLOWED_OVERRIDES = {
    "sort_by",
    "vote_average.gte",
    "vote_count.gte",
    "with_original_language",
    "with_origin_country",
    "with_keywords",
    "without_keywords",
    "without_genres",
    "with_runtime.gte",
    "with_runtime.lte",
    "primary_release_year",
    "first_air_date_year",
    "primary_release_date.gte",
    "primary_release_date.lte",
    "first_air_date.gte",
    "first_air_date.lte",
}

def _subscription_has_access(subscription) -> bool:
    """Check whether a subscription currently grants access."""

    now = datetime.now(timezone.utc)

    if subscription.status != "active":
        return False

    if (
        subscription.current_period_start is not None
        and subscription.current_period_start > now
    ):
        return False

    if (
        subscription.current_period_end is not None
        and subscription.current_period_end <= now
    ):
        return False

    if (
        subscription.cancel_at_period_end
        and subscription.current_period_end is None
    ):
        return False

    return True

def _normalise_title(item: dict, media_type: str) -> dict:
    is_movie = media_type == "movie"

    title = item.get("title") if is_movie else item.get("name")
    release_date = (
        item.get("release_date")
        if is_movie
        else item.get("first_air_date")
    )

    poster_path = item.get("poster_path")
    backdrop_path = item.get("backdrop_path")

    return {
        "tmdb_id": item["id"],
        "media_type": media_type,
        "title": title or "Untitled",
        "overview": item.get("overview") or "",
        "release_date": release_date or None,
        "genre_ids": item.get("genre_ids") or [],
        "original_language": item.get("original_language"),
        "poster_path": poster_path,
        "poster_url": (
            f"{IMAGE_BASE_URL}/w500{poster_path}"
            if poster_path else None
        ),
        "backdrop_path": backdrop_path,
        "backdrop_url": (
            f"{IMAGE_BASE_URL}/original{backdrop_path}"
            if backdrop_path else None
        ),
        "popularity": float(item.get("popularity") or 0),
        "vote_average": float(item.get("vote_average") or 0),
        "vote_count": int(item.get("vote_count") or 0),
        "adult": bool(item.get("adult", False)),
    }

def _get_continue_watching_results(
    db: Session,
    tmdb: TMDBClient,
    platform: StreamingPlatform,
    profile: Profile,
) -> list[dict]:
    """
    Return resumable titles for this profile and platform.

    Rules:
    - Only unfinished titles are displayed.
    - Titles expire after 72 hours without viewing activity.
    - A title is eligible only while fewer than five newer
      distinct title records exist for this profile/platform.
    - Completed titles still count as newer watches, but are
      never displayed in Continue Watching.
    """

    cutoff = datetime.now(timezone.utc) - timedelta(days=3)

    # Fetch the five most recently watched distinct titles first,
    # regardless of whether they are completed or unfinished.
    # Completed titles count towards pushing older titles out.
    recent_progress = db.scalars(
        select(WatchProgress)
        .join(
            ViewingSession,
            WatchProgress.last_session_id == ViewingSession.id,
        )
        .where(
            WatchProgress.profile_id == profile.id,
            ViewingSession.platform_id == platform.id,
        )
        .order_by(
            WatchProgress.last_watched_at.desc(),
            WatchProgress.tmdb_id.desc(),
        )
        .limit(5)
    ).all()

    results = []

    for progress in recent_progress:
        # Completed titles count as newer watches, but do not appear.
        if progress.status != "in_progress":
            continue

        # Expire unfinished titles after 72 hours.
        if progress.last_watched_at < cutoff:
            continue

        # Ignore invalid or effectively completed resume positions.
        if (
            progress.progress_ratio is not None
            and float(progress.progress_ratio) >= 0.90
        ):
            continue

        # Retrieve full TMDB metadata for the card.
        detail = tmdb.get(
            f"/{progress.media_type}/{progress.tmdb_id}"
        )

        if not detail or not detail.get("id"):
            continue

        normalized = _normalise_title(
            detail,
            progress.media_type,
        )

        # Detail endpoints return genre objects; expose names for cards.
        genres = detail.get("genres") or []

        result = {
            "tmdb_id": normalized["tmdb_id"],
            "media_type": normalized["media_type"],
            "title": normalized["title"],
            "release_date": normalized["release_date"],
            "poster_url": normalized["poster_url"],
            "backdrop_url": normalized["backdrop_url"],
            "genre_ids": [
                genre["id"]
                for genre in genres
                if genre.get("id") is not None
            ],
            "genres": [
                genre["name"]
                for genre in genres
                if genre.get("name")
            ],
            "position_seconds": (
                float(progress.position_seconds)
                if progress.position_seconds is not None
                else 0.0
            ),
            "duration_seconds": (
                float(progress.duration_seconds)
                if progress.duration_seconds is not None
                else None
            ),
            "progress_ratio": (
                float(progress.progress_ratio)
                if progress.progress_ratio is not None
                else None
            ),
            "progress_percent": (
                round(float(progress.progress_ratio) * 100)
                if progress.progress_ratio is not None
                else None
            ),
            "season_number": progress.season_number,
            "episode_number": progress.episode_number,
            "last_watched_at": (
                progress.last_watched_at.isoformat()
                if progress.last_watched_at
                else None
            ),
        }

        results.append(result)

    return results

def _strategy_sort(strategy: str, media_type: str) -> str:
    strategy = strategy.lower()

    if strategy in {"top_rated", "highest_rated"}:
        return "vote_average.desc"

    if strategy in {"recent", "latest", "new_releases"}:
        return (
            "primary_release_date.desc"
            if media_type == "movie"
            else "first_air_date.desc"
        )

    # Trending and popular both use popularity ordering here.
    # This avoids using TMDB's trending endpoint without a provider filter.
    return "popularity.desc"


def _get_provider_ids(
    db: Session,
    platform_id: UUID,
    region_code: str,
) -> list[int]:
    providers = db.scalars(
        select(PlatformProvider).where(
            PlatformProvider.platform_id == platform_id,
            PlatformProvider.provider_kind.in_(
                ["watch_provider", "tmdb_watch_provider"]
            ),
        )
    ).all()

    regional = [
        p for p in providers if p.region_code == region_code
    ]

    # A regional mapping takes precedence over a global mapping.
    candidates = regional or [
        p for p in providers if p.region_code is None
    ]

    if not candidates:
        raise HTTPException(
            status_code=400,
            detail=(
                "No TMDB watch-provider mapping is configured for "
                f"region {region_code}."
            ),
        )

    primary = [p for p in candidates if p.is_primary]
    selected = primary or candidates

    return list(dict.fromkeys(p.external_id for p in selected))


def _rating_for_title(
    tmdb: TMDBClient,
    media_type: str,
    tmdb_id: int,
    region_code: str,
) -> str | None:
    if media_type == "movie":
        data = tmdb.get(f"/movie/{tmdb_id}/release_dates")
        for country in data.get("results", []):
            if country.get("iso_3166_1") == region_code:
                ratings = [
                    entry.get("certification")
                    for entry in country.get("release_dates", [])
                    if entry.get("certification")
                ]
                if ratings:
                    return ratings[0]
    else:
        data = tmdb.get(f"/tv/{tmdb_id}/content_ratings")
        for country in data.get("results", []):
            if country.get("iso_3166_1") == region_code:
                return country.get("rating") or None

    return None

KIDS_DISCOVERY_GENRE_IDS = {16, 10751}

def _is_allowed_for_profile(
    item: dict,
    profile: Profile,
) -> bool:
    """
    Apply lightweight TMDB metadata filtering for kids profiles.

    This does not guarantee that every returned title is suitable
    for every child. It avoids per-title certification API requests.
    """

    # Never include titles explicitly flagged as adult by TMDB.
    if item.get("adult", False):
        return False

    # Adult profiles are not restricted to kids genres.
    if not profile.is_kids_profile:
        return True

    # For kids profiles, require TMDB's Family or Animation genre.
    genre_ids = item.get("genre_ids") or []

    try:
        genre_ids = {int(genre_id) for genre_id in genre_ids}
    except (TypeError, ValueError):
        return False

    return bool(genre_ids & KIDS_DISCOVERY_GENRE_IDS)

def _recommendation_score(
    item: dict,
    preferred_genres: set[int],
) -> float:
    genre_matches = len(
        set(item.get("genre_ids") or []) & preferred_genres
    )

    # Initial explainable ranking formula. We can tune this later
    # using actual viewing history and likes/dislikes.
    return (
        float(item.get("popularity") or 0)
        + float(item.get("vote_average") or 0) * 2
        + genre_matches * 10
    )




def _fetch_discovery(
    tmdb: TMDBClient,
    endpoint: str,
    media_type: str,
    provider_ids: list[int],
    region_code: str,
    language: str,
    page_size: int,
    strategy: str,
    genre_ids: list[int],
    overrides: dict,
    company_ids: list[int] | None = None,
    network_ids: list[int] | None = None,
    kids_mode: bool = False,
    force_refresh: bool = False,
    cache_status: dict | None = None,
) -> list[dict]:

    # ---------------------------------------------------------
    # 1. Build the TMDB discovery parameters
    # ---------------------------------------------------------

    params = {
        "watch_region": region_code,
        "with_watch_providers": "|".join(
            str(value) for value in sorted(set(provider_ids))
        ),
        "include_adult": "false",
        "include_video": "false",
        "language": language,
        "sort_by": _strategy_sort(strategy, media_type),
    }

    if genre_ids:
        params["with_genres"] = "|".join(
            str(value) for value in sorted(set(genre_ids))
        )

    if kids_mode:
        kids_genres = "|".join(
            str(value)
            for value in sorted(KIDS_DISCOVERY_GENRE_IDS)
        )

        if genre_ids:
            params["with_genres"] = (
                f"{params['with_genres']},{kids_genres}"
            )
        else:
            params["with_genres"] = kids_genres

    if company_ids:
        params["with_companies"] = "|".join(
            str(value) for value in sorted(set(company_ids))
        )

    if network_ids and media_type == "tv":
        params["with_networks"] = "|".join(
            str(value) for value in sorted(set(network_ids))
        )

    # Configuration cannot override provider, region, or adult filters.
    for key, value in (overrides or {}).items():
        if key in ALLOWED_OVERRIDES and value is not None:
            params[key] = value

    # ---------------------------------------------------------
    # 2. Determine how many TMDB pages we need
    # ---------------------------------------------------------

    candidate_target = max(1, min(page_size, 40))
    pages_to_fetch = (candidate_target + 19) // 20

    # ---------------------------------------------------------
    # 3. Generate a unique cache key
    # ---------------------------------------------------------

    cache_identity = {
        "endpoint": endpoint,
        "media_type": media_type,
        "params": params,
        "candidate_target": candidate_target,
        "pages_to_fetch": pages_to_fetch,
        "kids_mode": kids_mode,
    }

    # Convert the query configuration into consistent JSON.
    cache_identity_json = json.dumps(
        cache_identity,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )

    # Hash the configuration so our Redis keys remain short.
    cache_hash = hashlib.sha256(
        cache_identity_json.encode("utf-8")
    ).hexdigest()

    cache_key = f"tmdb:discovery:{cache_hash}"

    # ---------------------------------------------------------
    # 4. Check Redis before contacting TMDB
    # ---------------------------------------------------------

    if not force_refresh:
        cached_results = get_cache(cache_key)

        if isinstance(cached_results, list):
            logger.info(
                "TMDB DISCOVERY | Using cached results | "
                "media_type=%s | strategy=%s | results=%s",
                media_type,
                strategy,
                len(cached_results),
            )
            return cached_results
    else:
        logger.info(
            "TMDB DISCOVERY | Force refresh requested | "
            "media_type=%s | strategy=%s",
            media_type,
            strategy,
        )

    # ---------------------------------------------------------
    # 5. Cache miss: fetch the results from TMDB
    # ---------------------------------------------------------

    logger.info(
        "TMDB DISCOVERY | Fetching from TMDB | "
        "media_type=%s | strategy=%s | pages=%s",
        media_type,
        strategy,
        pages_to_fetch,
    )

    results_by_id = {}

    for page_number in range(1, pages_to_fetch + 1):

        page_params = {
            **params,
            "page": page_number,
        }

        data = tmdb.get(
            endpoint,
            params=page_params,
        )

        page_results = data.get("results", [])

        if not page_results:
            break

        for item in page_results:

            item_id = item.get("id")

            if item_id is not None:
                results_by_id[item_id] = item

        # Stop early if TMDB reports that there are no more pages.
        total_pages = data.get("total_pages", page_number)

        if page_number >= total_pages:
            break

    results = list(results_by_id.values())


    # ---------------------------------------------------------
    # 6. Save the results in Redis for 30 minutes
    # ---------------------------------------------------------

    cache_saved = set_cache(
        key=cache_key,
        value=results,
        ttl=1800,
    )

    # Allow the scheduled cache refresh service to inspect
    # whether Redis successfully saved this discovery query.
    if cache_status is not None:
        cache_status["saved"] = cache_saved
        cache_status["cache_key"] = cache_key
        cache_status["result_count"] = len(results)

    if cache_saved:
        logger.info(
            "TMDB DISCOVERY | Results cached successfully | "
            "media_type=%s | strategy=%s | results=%s",
            media_type,
            strategy,
            len(results),
        )
    else:
        logger.warning(
            "TMDB DISCOVERY | Could not cache results | "
            "media_type=%s | strategy=%s",
            media_type,
            strategy,
        )

    return results


def _get_all_provider_ids(
    db: Session,
    platform_id: UUID,
    region_code: str,
) -> list[int]:
    """
    Return every applicable watch-provider ID for a platform.
    Unlike _get_provider_ids(), this does not restrict the
    result to primary providers.
    """
    providers = db.scalars(
        select(PlatformProvider).where(
            PlatformProvider.platform_id == platform_id,
            PlatformProvider.provider_kind.in_(
                ["watch_provider", "tmdb_watch_provider"]
            ),
        )
    ).all()

    regional = [
        provider for provider in providers
        if provider.region_code == region_code
    ]

    candidates = regional or [
        provider for provider in providers
        if provider.region_code is None
    ]

    return list(dict.fromkeys(
        int(provider.external_id)
        for provider in candidates
        if provider.external_id is not None
    ))


def _merge_unified_titles(
    destination: dict,
    raw_item: dict,
    media_type: str,
    platform: StreamingPlatform,
) -> None:
    """
    Merge duplicate TMDB titles while recording every platform
    that returned the title for its configured watch provider.
    """
    tmdb_id = raw_item.get("id")

    if tmdb_id is None:
        return

    if media_type == "movie" and not raw_item.get("title"):
        return

    if media_type == "tv" and not raw_item.get("name"):
        return

    key = (media_type, int(tmdb_id))

    if key not in destination:
        title = _normalise_title(raw_item, media_type)
        title["available_on"] = []

        destination[key] = title

    available_on = destination[key]["available_on"]

    platform_entry = {
        "platform_id": str(platform.id),
        "platform_name": platform.name,
        "platform_slug": platform.slug,
    }

    if not any(
        item["platform_id"] == platform_entry["platform_id"]
        for item in available_on
    ):
        available_on.append(platform_entry)




def _unified_discovery_collection(
    db: Session,
    tmdb: TMDBClient,
    platforms: list[StreamingPlatform],
    profile: Profile,
    media_types: list[str],
    genre_ids: list[int] | None = None,
    overrides: dict | None = None,
    strategy: str = "popular",
    page_size: int = 20,
) -> list[dict]:
    """
    Discover titles across entitled platforms using combined
    provider IDs.

    Platforms are grouped by region and language because TMDB
    accepts only one watch_region and language per request.

    Provider IDs are combined separately for movies and TV,
    using only platforms that support the requested media type.

    Shared results are not assigned a false per-title
    available_on attribution. Exact availability requires
    provider verification.
    """

    genre_ids = genre_ids or []
    overrides = overrides or {}

    # -------------------------------------------------
    # 1. Load platform configurations
    # -------------------------------------------------

    platform_ids = [platform.id for platform in platforms]

    if not platform_ids:
        return []

    configs = db.scalars(
        select(PlatformProfile).where(
            PlatformProfile.platform_id.in_(platform_ids),
            PlatformProfile.enabled.is_(True),
        )
    ).all()

    config_by_platform = {
        config.platform_id: config
        for config in configs
    }

    # Only include platforms with an enabled configuration.
    eligible_platforms = [
        platform
        for platform in platforms
        if platform.id in config_by_platform
    ]

    if not eligible_platforms:
        return []

    eligible_platform_ids = [
        platform.id
        for platform in eligible_platforms
    ]

    # -------------------------------------------------
    # 2. Group platforms by region and language
    # -------------------------------------------------

    groups = {}

    for platform in eligible_platforms:
        config = config_by_platform[platform.id]

        region_code = (
            config.region_code or settings.tmdb_region
        )

        language = (
            config.language or settings.tmdb_language
        )

        group_key = (region_code, language)

        groups.setdefault(
            group_key,
            {
                "platforms": [],
                "regional_by_platform": {},
                "global_by_platform": {},
            },
        )["platforms"].append(platform)

    # -------------------------------------------------
    # 3. Load provider mappings in one database query
    # -------------------------------------------------

    provider_rows = db.scalars(
        select(PlatformProvider).where(
            PlatformProvider.platform_id.in_(
                eligible_platform_ids
            ),
            PlatformProvider.provider_kind.in_(
                ["watch_provider", "tmdb_watch_provider"]
            ),
        )
    ).all()

    for provider in provider_rows:

        config = config_by_platform.get(
            provider.platform_id
        )

        if config is None:
            continue

        region_code = (
            config.region_code or settings.tmdb_region
        )

        language = (
            config.language or settings.tmdb_language
        )

        group = groups.get((region_code, language))

        if group is None:
            continue

        if provider.external_id is None:
            continue

        provider_mapping = (
            int(provider.external_id),
            provider.is_primary,
        )

        # Regional mappings take priority.
        if provider.region_code == region_code:

            group["regional_by_platform"].setdefault(
                provider.platform_id,
                [],
            ).append(provider_mapping)

        # Global mappings are fallback mappings.
        elif provider.region_code is None:

            group["global_by_platform"].setdefault(
                provider.platform_id,
                [],
            ).append(provider_mapping)

    # -------------------------------------------------
    # 4. Discover titles for each region/language group
    # -------------------------------------------------

    merged = {}

    for (region_code, language), group in groups.items():

        # Process movies and TV separately.
        for media_type in media_types:

            if media_type not in {"movie", "tv"}:
                continue

            # -----------------------------------------
            # 4A. Identify platforms supporting this type
            # -----------------------------------------

            supported_platforms = [
                platform
                for platform in group["platforms"]
                if (
                    platform.supports_movies
                    if media_type == "movie"
                    else platform.supports_tv_shows
                )
            ]

            if not supported_platforms:
                continue

            # -----------------------------------------
            # 4B. Build provider IDs for this media type
            # -----------------------------------------

            provider_ids = set()

            for platform in supported_platforms:

                regional = group[
                    "regional_by_platform"
                ].get(platform.id, [])

                global_mappings = group[
                    "global_by_platform"
                ].get(platform.id, [])

                # Use regional mappings first.
                # Fall back to global mappings only when
                # no regional mapping exists for the platform.
                candidates = regional or global_mappings

                # Prefer primary providers when available.
                primary = [
                    provider_id
                    for provider_id, is_primary in candidates
                    if is_primary
                ]

                selected = primary or [
                    provider_id
                    for provider_id, _ in candidates
                ]

                provider_ids.update(selected)

            if not provider_ids:
                continue

            # -----------------------------------------
            # 4C. Select TMDB discovery endpoint
            # -----------------------------------------

            endpoint = (
                "/discover/movie"
                if media_type == "movie"
                else "/discover/tv"
            )

            # -----------------------------------------
            # 4D. Prepare media-specific overrides
            # -----------------------------------------

            effective_overrides = dict(overrides)

            # Remove date filters that do not apply
            # to the selected media type.
            if media_type == "movie":

                effective_overrides.pop(
                    "first_air_date.gte",
                    None,
                )

                effective_overrides.pop(
                    "first_air_date.lte",
                    None,
                )

            else:

                effective_overrides.pop(
                    "primary_release_date.gte",
                    None,
                )

                effective_overrides.pop(
                    "primary_release_date.lte",
                    None,
                )

            # -----------------------------------------
            # 4E. Fetch discovery results from TMDB
            # -----------------------------------------

            results = _fetch_discovery(
                tmdb=tmdb,
                endpoint=endpoint,
                media_type=media_type,
                provider_ids=sorted(provider_ids),
                region_code=region_code,
                language=language,
                page_size=page_size,
                strategy=strategy,
                genre_ids=genre_ids,
                overrides=effective_overrides,
                kids_mode=profile.is_kids_profile,
            )

            # -----------------------------------------
            # 4F. Filter and merge results
            # -----------------------------------------

            for item in results:

                if not item.get("id"):
                    continue

                if media_type == "movie" and not item.get("title"):
                    continue

                if media_type == "tv" and not item.get("name"):
                    continue

                if not _is_allowed_for_profile(
                    item,
                    profile,
                ):
                    continue

                key = (
                    media_type,
                    int(item["id"]),
                )

                if key not in merged:

                    merged[key] = _normalise_title(
                        item,
                        media_type,
                    )

    # -------------------------------------------------
    # 5. Convert merged results into a list
    # -------------------------------------------------

    results = list(merged.values())

    # -------------------------------------------------
    # 6. Apply the requested sorting strategy
    # -------------------------------------------------

    if strategy == "top_picks":

        preferences = profile.preferences or {}

        preferred_genres = {
            int(value)
            for value in preferences.get(
                "preferred_genres",
                [],
            )
            if str(value).isdigit()
        }

        results.sort(
            key=lambda item: _recommendation_score(
                item,
                preferred_genres,
            ),
            reverse=True,
        )

    elif strategy in {
        "newest",
        "recent",
        "latest",
        "new_releases",
    }:

        results.sort(
            key=lambda item: item.get("release_date") or "",
            reverse=True,
        )

    else:

        results.sort(
            key=lambda item: item.get("popularity", 0),
            reverse=True,
        )

    # -------------------------------------------------
    # 7. Return the requested number of results
    # -------------------------------------------------

    return results[:page_size]


def _get_section_preferences(profile: Profile) -> dict:
    """
    Return the profile's learned genre and keyword preferences.

    The stored preference objects are passed through without changing
    their weights or names.
    """
    preferences = profile.preferences or {}

    return {
        "genre_preferences": preferences.get("genre_preferences") or [],
        "keyword_preferences": preferences.get("keyword_preferences") or [],
    }


def _get_preference_ids(preferences: list[dict], id_key: str) -> list[int]:
    """Extract valid integer IDs from preference objects."""
    results = []

    for item in preferences:
        if not isinstance(item, dict):
            continue

        value = item.get(id_key)

        try:
            value = int(value)
        except (TypeError, ValueError):
            continue

        if value not in results:
            results.append(value)

    return results


def _get_preference_source(profile_preferences: dict, has_defaults: bool = False) -> str:
    """Describe whether a section uses learned or default preferences."""
    has_profile_preferences = bool(
        profile_preferences.get("genre_preferences")
        or profile_preferences.get("keyword_preferences")
    )

    if has_profile_preferences and has_defaults:
        return "mixed"

    if has_profile_preferences:
        return "profile"

    return "default"



def _build_unified_content_sources(
    db: Session,
    platforms: list[StreamingPlatform],
) -> list[dict]:
    """
    Build region/language-specific discovery sources from entitled
    platforms only.

    This function performs database queries only. It does not call TMDB.
    """

    if not platforms:
        return []

    platform_ids = [platform.id for platform in platforms]

    configs = db.scalars(
        select(PlatformProfile).where(
            PlatformProfile.platform_id.in_(platform_ids),
            PlatformProfile.enabled.is_(True),
        )
    ).all()

    config_by_platform = {
        config.platform_id: config
        for config in configs
    }

    eligible_platforms = [
        platform
        for platform in platforms
        if platform.id in config_by_platform
    ]

    if not eligible_platforms:
        return []

    platform_by_id = {
        platform.id: platform
        for platform in eligible_platforms
    }

    groups = {}

    for platform in eligible_platforms:
        config = config_by_platform[platform.id]

        region_code = config.region_code or settings.tmdb_region
        language = config.language or settings.tmdb_language

        group_key = (region_code, language)

        if group_key not in groups:
            groups[group_key] = {
                "region_code": region_code,
                "language": language,
                "platforms": [],
                "regional_providers": {},
                "global_providers": {},
                "production_companies": {},
                "networks": {},
            }

        groups[group_key]["platforms"].append(platform)

    # ---------------------------------------------------------
    # Load watch provider mappings.
    # ---------------------------------------------------------
    provider_rows = db.scalars(
        select(PlatformProvider).where(
            PlatformProvider.platform_id.in_(
                [platform.id for platform in eligible_platforms]
            ),
            PlatformProvider.provider_kind.in_(
                ["watch_provider", "tmdb_watch_provider"]
            ),
        )
    ).all()

    for provider in provider_rows:
        config = config_by_platform.get(provider.platform_id)

        if config is None or provider.external_id is None:
            continue

        region_code = config.region_code or settings.tmdb_region
        language = config.language or settings.tmdb_language

        group = groups.get((region_code, language))

        if group is None:
            continue

        platform = platform_by_id.get(provider.platform_id)

        if platform is None:
            continue

        mapping = {
            "provider_id": int(provider.external_id),
            "provider_name": provider.platform_name,
            "platform_id": str(platform.id),
            "platform_name": platform.name,
            "is_primary": bool(provider.is_primary),
        }

        if provider.region_code == region_code:
            group["regional_providers"].setdefault(
                provider.platform_id, []
            ).append(mapping)

        elif provider.region_code is None:
            group["global_providers"].setdefault(
                provider.platform_id, []
            ).append(mapping)

    # ---------------------------------------------------------
    # Load production companies.
    # ---------------------------------------------------------
    company_rows = db.scalars(
        select(PlatformCompany).where(
            PlatformCompany.platform_id.in_(
                [platform.id for platform in eligible_platforms]
            ),
            PlatformCompany.include_in_discovery.is_(True),
        )
    ).all()

    for company in company_rows:
        platform = platform_by_id.get(company.platform_id)

        if platform is None or not platform.supports_movies:
            continue

        config = config_by_platform[platform.id]
        region_code = config.region_code or settings.tmdb_region
        language = config.language or settings.tmdb_language

        group = groups.get((region_code, language))

        if group is None or company.tmdb_company_id is None:
            continue

        company_id = int(company.tmdb_company_id)

        entry = group["production_companies"].setdefault(
            company_id,
            {
                "company_id": company_id,
                "company_name": company.company_name,
                "platform_ids": [],
                "relation_types": [],
                "confidence": company.confidence,
            },
        )

        platform_id = str(platform.id)

        if platform_id not in entry["platform_ids"]:
            entry["platform_ids"].append(platform_id)

        if (
            company.relation_type
            and company.relation_type not in entry["relation_types"]
        ):
            entry["relation_types"].append(company.relation_type)

    # ---------------------------------------------------------
    # Load TV networks.
    # ---------------------------------------------------------
    network_rows = db.scalars(
        select(PlatformNetwork).where(
            PlatformNetwork.platform_id.in_(
                [platform.id for platform in eligible_platforms]
            ),
            PlatformNetwork.include_in_discovery.is_(True),
        )
    ).all()

    for network in network_rows:
        platform = platform_by_id.get(network.platform_id)

        if platform is None or not platform.supports_tv_shows:
            continue

        config = config_by_platform[platform.id]
        region_code = config.region_code or settings.tmdb_region
        language = config.language or settings.tmdb_language

        group = groups.get((region_code, language))

        if group is None or network.tmdb_network_id is None:
            continue

        network_id = int(network.tmdb_network_id)

        entry = group["networks"].setdefault(
            network_id,
            {
                "network_id": network_id,
                "network_name": network.network_name,
                "platform_ids": [],
            },
        )

        platform_id = str(platform.id)

        if platform_id not in entry["platform_ids"]:
            entry["platform_ids"].append(platform_id)

    # ---------------------------------------------------------
    # Build final region/language groups.
    # ---------------------------------------------------------
    results = []

    for group in groups.values():

        # Each platform now has its own descriptive entry.
        platform_entries = [
            {
                "platform_id": str(platform.id),
                "platform_name": platform.name,
            }
            for platform in group["platforms"]
        ]

        # Build individual provider mappings.
        provider_entries = {}

        for platform in group["platforms"]:
            regional = group["regional_providers"].get(
                platform.id, []
            )

            global_mappings = group["global_providers"].get(
                platform.id, []
            )

            # Regional mappings take precedence over global mappings.
            candidates = regional or global_mappings

            for mapping in candidates:
                provider_key = (
                    mapping["provider_id"],
                    mapping["platform_id"],
                )

                provider_entries[provider_key] = mapping

        results.append({
            "region_code": group["region_code"],
            "language": group["language"],
            "platforms": platform_entries,
            "watch_providers": list(provider_entries.values()),
            "production_companies": list(
                group["production_companies"].values()
            ),
            "networks": list(group["networks"].values()),
        })

    return results


def _filter_content_sources(
    source_groups: list[dict],
    media_type: str,
) -> list[dict]:
    """
    Return only the source types relevant to a content section.
    """

    results = []

    for group in source_groups:
        entry = {
            "region_code": group["region_code"],
            "language": group["language"],
            "platforms": group["platforms"],
            "watch_providers": group["watch_providers"],
        }

        if media_type == "movie":
            entry["production_companies"] = group[
                "production_companies"
            ]

        elif media_type == "tv":
            entry["networks"] = group["networks"]

        results.append(entry)

    return results

def _build_recommended_queries(
    source_groups: list[dict],
    media_type: str,
    profile_preferences: dict,
    default_genre_ids: list[int] | None = None,
) -> list[dict]:
    """
    Generate TMDB query templates for the frontend.

    No TMDB requests are performed here.
    """

    endpoint = (
        "/discover/movie"
        if media_type == "movie"
        else "/discover/tv"
    )

    genre_ids = _get_preference_ids(
        profile_preferences.get("genre_preferences", []),
        "genre_id",
    )

    keyword_ids = _get_preference_ids(
        profile_preferences.get("keyword_preferences", []),
        "keyword_id",
    )

    default_genre_ids = default_genre_ids or []

    # Cartoons must always retain their Animation/Family filters.
    if default_genre_ids:
        genre_ids = list(dict.fromkeys(
            default_genre_ids + genre_ids
        ))

    queries = []

    for group in source_groups:
        provider_ids = [
            item["provider_id"]
            for item in group["watch_providers"]
        ]

        base_parameters = {
            "watch_region": group["region_code"],
            "language": group["language"],
            "include_adult": False,
            "sort_by": "popularity.desc",
        }

        if provider_ids:
            base_parameters["with_watch_providers"] = "|".join(
                str(value) for value in sorted(set(provider_ids))
            )

        # Personalised genre discovery.
        if genre_ids:
            parameters = dict(base_parameters)
            parameters["with_genres"] = "|".join(
                str(value) for value in genre_ids
            )

            queries.append({
                "name": "Personalised " + (
                    "Movies" if media_type == "movie" else "TV Shows"
                ),
                "endpoint": endpoint,
                "parameters": parameters,
            })

        # Personalised keyword discovery.
        if keyword_ids and not default_genre_ids:
            parameters = dict(base_parameters)
            parameters["with_keywords"] = "|".join(
                str(value) for value in keyword_ids
            )

            queries.append({
                "name": "Keyword Recommendations",
                "endpoint": endpoint,
                "parameters": parameters,
            })

        # Platform production-company discovery.
        if media_type == "movie":
            company_ids = [
                item["company_id"]
                for item in group["production_companies"]
            ]

            if company_ids:
                parameters = dict(base_parameters)
                parameters["with_companies"] = "|".join(
                    str(value) for value in sorted(set(company_ids))
                )

                queries.append({
                    "name": "Platform Production Companies",
                    "endpoint": endpoint,
                    "parameters": parameters,
                })

        # Platform network discovery.
        if media_type == "tv":
            network_ids = [
                item["network_id"]
                for item in group["networks"]
            ]

            if network_ids:
                parameters = dict(base_parameters)
                parameters["with_networks"] = "|".join(
                    str(value) for value in sorted(set(network_ids))
                )

                queries.append({
                    "name": "Platform Networks",
                    "endpoint": endpoint,
                    "parameters": parameters,
                })

        # General popular discovery.
        queries.append({
            "name": "Popular " + (
                "Movies" if media_type == "movie" else "TV Shows"
            ),
            "endpoint": endpoint,
            "parameters": dict(base_parameters),
        })

    return queries


def _get_unified_continue_watching(
    db: Session,
    platforms: list[StreamingPlatform],
    profile: Profile,
) -> list[dict]:
    """
    Return the five most recently watched distinct title records
    across all entitled platforms.

    Completed titles still count towards the five-record limit.
    Only unfinished titles watched within the last 72 hours appear.
    """

    if not platforms:
        return []

    platform_ids = [platform.id for platform in platforms]

    recent_rows = db.execute(
        select(WatchProgress, StreamingPlatform)
        .join(
            ViewingSession,
            WatchProgress.last_session_id == ViewingSession.id,
        )
        .join(
            StreamingPlatform,
            StreamingPlatform.id == ViewingSession.platform_id,
        )
        .where(
            WatchProgress.profile_id == profile.id,
            ViewingSession.platform_id.in_(platform_ids),
            StreamingPlatform.is_active.is_(True),
        )
        .order_by(
            WatchProgress.last_watched_at.desc(),
            WatchProgress.tmdb_id.desc(),
        )
        .limit(5)
    ).all()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)

    eligible = []

    for progress, platform in recent_rows:
        if progress.status != "in_progress":
            continue

        if progress.last_watched_at is None:
            continue

        last_watched_at = progress.last_watched_at

        # Support database timestamps that may be timezone-naive.
        if last_watched_at.tzinfo is None:
            last_watched_at = last_watched_at.replace(
                tzinfo=timezone.utc
            )

        if last_watched_at < cutoff:
            continue

        if (
            progress.progress_ratio is not None
            and float(progress.progress_ratio) >= 0.90
        ):
            continue

        if progress.media_type not in {"movie", "tv"}:
            continue

        eligible.append((progress, platform))

    if not eligible:
        return []

    results = []
    seen_titles = set()

    with TMDBClient() as tmdb:
        for progress, platform in eligible:
            title_key = (
                progress.media_type,
                int(progress.tmdb_id),
            )

            if title_key in seen_titles:
                continue

            seen_titles.add(title_key)

            try:
                detail = tmdb.get(
                    f"/{progress.media_type}/{progress.tmdb_id}"
                )
            except Exception:
                logger.exception(
                    "Continue Watching metadata lookup failed: "
                    "media_type=%s tmdb_id=%s",
                    progress.media_type,
                    progress.tmdb_id,
                )
                continue

            if not detail or not detail.get("id"):
                continue

            normalized = _normalise_title(
                detail,
                progress.media_type,
            )

            genres = detail.get("genres") or []

            results.append({
                "tmdb_id": normalized["tmdb_id"],
                "media_type": normalized["media_type"],
                "title": normalized["title"],
                "release_date": normalized["release_date"],
                "poster_url": normalized["poster_url"],
                "backdrop_url": normalized["backdrop_url"],
                "genre_ids": [
                    genre["id"]
                    for genre in genres
                    if genre.get("id") is not None
                ],
                "genres": [
                    genre["name"]
                    for genre in genres
                    if genre.get("name")
                ],
                "position_seconds": (
                    float(progress.position_seconds)
                    if progress.position_seconds is not None
                    else 0.0
                ),
                "duration_seconds": (
                    float(progress.duration_seconds)
                    if progress.duration_seconds is not None
                    else None
                ),
                "progress_ratio": (
                    float(progress.progress_ratio)
                    if progress.progress_ratio is not None
                    else None
                ),
                "progress_percent": (
                    round(float(progress.progress_ratio) * 100)
                    if progress.progress_ratio is not None
                    else None
                ),
                "season_number": progress.season_number,
                "episode_number": progress.episode_number,
                "last_watched_at": (
                    progress.last_watched_at.isoformat()
                    if progress.last_watched_at
                    else None
                ),
                "platform": {
                    "id": str(platform.id),
                    "name": platform.name,
                    "slug": platform.slug,
                },
            })

    return results



def get_unified_home(
    db: Session,
    account_id: UUID,
    profile: Profile,
) -> dict:
    """
    Return the unified home response.

    TMDB title discovery is handled by the frontend.

    The backend supplies:
    - Discovery sources from entitled platforms.
    - Profile preferences and section-specific defaults.
    - Home slider templates.
    - Continue Watching titles only.
    - Available platforms and live-TV channels.

    This function does not fetch movie, TV show, or cartoon
    discovery collections from TMDB.
    """

    # -----------------------------------------------------
    # 1. Find the customer's active subscription.
    # -----------------------------------------------------
    subscriptions = db.scalars(
        select(Subscription)
        .where(Subscription.account_id == account_id)
        .order_by(Subscription.created_at.desc())
    ).all()

    subscription = next(
        (
            item for item in subscriptions
            if _subscription_has_access(item)
        ),
        None,
    )

    plan = None

    if subscription is not None:
        plan = db.get(Plan, subscription.plan_id)

        if plan is None:
            subscription = None

    # -----------------------------------------------------
    # 2. Determine included platforms and features.
    # -----------------------------------------------------
    entitled_platform_ids = set()
    live_tv_enabled = False

    if subscription is not None and plan is not None:

        entitlement_platform_ids = db.scalars(
            select(PlanEntitlement.platform_id).where(
                PlanEntitlement.plan_id == plan.id
            )
        ).all()

        entitled_platform_ids = {
            str(platform_id)
            for platform_id in entitlement_platform_ids
        }

        live_tv_enabled = (
            db.scalar(
                select(PlanFeature.is_enabled).where(
                    PlanFeature.plan_id == plan.id,
                    PlanFeature.feature_code == "live_tv",
                )
            )
            is True
        )

    # -----------------------------------------------------
    # 3. Return active platforms with their access status.
    # -----------------------------------------------------
    platforms = db.scalars(
        select(StreamingPlatform)
        .where(StreamingPlatform.is_active.is_(True))
        .order_by(StreamingPlatform.display_order.asc())
    ).all()

    platform_availability = {}
    all_platforms = []

    for platform in platforms:

        is_available = (
            plan is not None
            and str(platform.id) in entitled_platform_ids
        )

        platform_availability[str(platform.id)] = is_available

        all_platforms.append({
            "id": str(platform.id),
            "name": platform.name,
            "slug": platform.slug,
            "logo_url": platform.logo_url,
            "is_available": is_available,
            "availability_status": (
                "available" if is_available else "not_included"
            ),
        })

    # Only entitled, active platforms contribute discovery sources
    # and Continue Watching records.
    entitled_platforms = [
        platform
        for platform in platforms
        if str(platform.id) in entitled_platform_ids
    ]

    # -----------------------------------------------------
    # 4. Return live-TV channels grouped by platform.
    # -----------------------------------------------------
    channel_rows = db.execute(
        select(PlatformLiveChannel, StreamingPlatform)
        .join(
            StreamingPlatform,
            StreamingPlatform.id == PlatformLiveChannel.platform_id,
        )
        .where(
            PlatformLiveChannel.is_active.is_(True),
            StreamingPlatform.is_active.is_(True),
        )
        .order_by(
            StreamingPlatform.display_order.asc(),
            PlatformLiveChannel.display_order.asc(),
            PlatformLiveChannel.name.asc(),
        )
    ).all()

    live_tv_by_platform = {}

    for channel, channel_platform in channel_rows:

        platform_id = str(channel_platform.id)

        channel_is_available = (
            channel_platform.is_active
            and platform_availability.get(platform_id, False)
            and live_tv_enabled
        )

        if platform_id not in live_tv_by_platform:
            live_tv_by_platform[platform_id] = {
                "platform_id": platform_id,
                "platform_name": channel_platform.name,
                "platform_slug": channel_platform.slug,
                "is_available": channel_is_available,
                "availability_status": (
                    "available"
                    if channel_is_available
                    else "not_included"
                ),
                "channels": [],
            }

        live_tv_by_platform[platform_id]["channels"].append({
            "id": str(channel.id),
            "channel_key": channel.channel_key,
            "name": channel.name,
            "logo_url": channel.logo_url,
            "stream_url": channel.stream_url,
            "channel_number": channel.channel_number,
            "display_order": channel.display_order,
            "category": channel.category,
            "is_news_channel": channel.is_news_channel,
        })

    live_tv_platforms = list(live_tv_by_platform.values())

    live_tv_channel_count = sum(
        len(platform["channels"])
        for platform in live_tv_platforms
    )

    # -----------------------------------------------------
    # 5. Load the profile's learned preferences.
    # -----------------------------------------------------
    profile_preferences = _get_section_preferences(profile)

    # Keep the two preference categories available separately.
    genre_preferences = profile_preferences.get(
        "genre_preferences", []
    ) or []

    keyword_preferences = profile_preferences.get(
        "keyword_preferences", []
    ) or []

    has_profile_preferences = bool(
        genre_preferences or keyword_preferences
    )

    profile_preference_source = (
        "profile" if has_profile_preferences else "default"
    )

    # -----------------------------------------------------
    # 6. Build discovery sources from entitled platforms.
    # -----------------------------------------------------
    source_groups = _build_unified_content_sources(
        db=db,
        platforms=entitled_platforms,
    )

    # Movies: watch providers and production companies.
    movie_sources = _filter_content_sources(
        source_groups=source_groups,
        media_type="movie",
    )

    # TV Shows: watch providers and TV networks.
    tv_sources = _filter_content_sources(
        source_groups=source_groups,
        media_type="tv",
    )

    # Cartoons: watch providers only.
    # The frontend applies the mandatory Animation and Family
    # genre filters separately.
    cartoon_sources = []

    for group in source_groups:
        cartoon_sources.append({
            "region_code": group["region_code"],
            "language": group["language"],
            "platforms": group["platforms"],
            "watch_providers": group["watch_providers"],
        })

    # Home can use both movie and TV discovery sources.
    home_sources = source_groups

    # -----------------------------------------------------
    # 7. Home defaults and slider templates.
    # -----------------------------------------------------
    home_default_preferences = {
        "sort_by": "popularity.desc",
        "include_adult": False,
        "include_trending": True,
    }

    home_slider_templates = [
        {
            "key": "hero",
            "title": "Hero",
            "media_types": ["movie", "tv"],
            "genre_ids": [],
            "strategy": "popular",
            "limit": 10,
        },
        {
            "key": "new_this_week",
            "title": "New This Week",
            "media_types": ["movie", "tv"],
            "genre_ids": [],
            "strategy": "newest",
            "limit": 20,
        },
        {
            "key": "trending_now",
            "title": "Trending Now",
            "media_types": ["movie", "tv"],
            "genre_ids": [],
            "strategy": "trending",
            "limit": 20,
        },
        {
            "key": "top_picks_for_you",
            "title": "Top Picks for You",
            "media_types": ["movie", "tv"],
            "genre_ids": [],
            "strategy": "personalised",
            "limit": 20,
        },
        {
            "key": "action",
            "title": "Action",
            "media_types": ["movie", "tv"],
            "genre_ids": [28, 10759],
            "strategy": "popular",
            "limit": 20,
        },
        {
            "key": "comedy",
            "title": "Comedy",
            "media_types": ["movie", "tv"],
            "genre_ids": [35],
            "strategy": "popular",
            "limit": 20,
        },
        {
            "key": "sci_fi",
            "title": "Sci-Fi",
            "media_types": ["movie", "tv"],
            "genre_ids": [878, 10765],
            "strategy": "popular",
            "limit": 20,
        },
        {
            "key": "thrillers",
            "title": "Thrillers",
            "media_types": ["movie"],
            "genre_ids": [53],
            "strategy": "popular",
            "limit": 20,
        },
        {
            "key": "horror",
            "title": "Horror",
            "media_types": ["movie"],
            "genre_ids": [27],
            "strategy": "popular",
            "limit": 20,
        },
    ]

    # -----------------------------------------------------
    # 8. Movies defaults and recommended queries.
    # -----------------------------------------------------
    movie_default_preferences = {
        "genre_ids": [],
        "keyword_ids": [],
        "sort_by": "popularity.desc",
        "include_adult": False,
    }

    movie_queries = _build_recommended_queries(
        source_groups=source_groups,
        media_type="movie",
        profile_preferences=profile_preferences,
    )

    # -----------------------------------------------------
    # 9. TV Shows defaults and recommended queries.
    # -----------------------------------------------------
    tv_default_preferences = {
        "genre_ids": [],
        "keyword_ids": [],
        "sort_by": "popularity.desc",
        "include_adult": False,
    }

    tv_queries = _build_recommended_queries(
        source_groups=source_groups,
        media_type="tv",
        profile_preferences=profile_preferences,
    )

    # -----------------------------------------------------
    # 10. Cartoons defaults and recommended queries.
    # -----------------------------------------------------
    cartoon_default_preferences = {
        "movie_genre_ids": [16, 10751],
        "tv_genre_ids": [16, 10751],
        "sort_by": "popularity.desc",
        "include_adult": False,
    }

    cartoon_movie_queries = _build_recommended_queries(
        source_groups=source_groups,
        media_type="movie",
        profile_preferences=profile_preferences,
        default_genre_ids=[16, 10751],
    )

    cartoon_tv_queries = _build_recommended_queries(
        source_groups=source_groups,
        media_type="tv",
        profile_preferences=profile_preferences,
        default_genre_ids=[16, 10751],
    )

    cartoon_preference_source = (
        "mixed" if has_profile_preferences else "default"
    )

    # -----------------------------------------------------
    # 11. Retrieve Continue Watching titles only.
    # -----------------------------------------------------
    continue_watching = _get_unified_continue_watching(
        db=db,
        platforms=entitled_platforms,
        profile=profile,
    )

    # -----------------------------------------------------
    # 12. Build the final response.
    # -----------------------------------------------------
    return {
        "user": {
            "account_id": str(account_id),
            "profile_id": str(profile.id),
            "name": profile.name,
            "avatar_url": profile.avatar_key,
            "account_type": (
                "Kids" if profile.is_kids_profile else "Adult"
            ),
        },

        "home": {
            "profile_preferences": profile_preferences,
            "default_preferences": home_default_preferences,
            "preference_source": profile_preference_source,
            "discovery_strategy": {
                "media_types": ["movie", "tv"],
                "title_fetching": "frontend",
                "content_sources": home_sources,
                "discovery_priorities": [
                    "continue_watching",
                    "profile_preferences",
                    "trending",
                    "popular",
                ],
                "slider_templates": home_slider_templates,
            },
            "continue_watching": continue_watching,
        },

        "all_platforms": all_platforms,

        "live_tv": {
            "enabled": live_tv_enabled,
            "count": live_tv_channel_count,
            "platforms": live_tv_platforms,
        },

        "movies": {
            "profile_preferences": profile_preferences,
            "default_preferences": movie_default_preferences,
            "preference_source": profile_preference_source,
            "discovery_strategy": {
                "media_type": "movie",
                "title_fetching": "frontend",
                "content_sources": movie_sources,
                "discovery_priorities": [
                    "profile_genres",
                    "profile_keywords",
                    "platform_production_companies",
                    "popular",
                    "top_rated",
                    "new_releases",
                ],
                "recommended_queries": movie_queries,
            },
        },

        "tv_shows": {
            "profile_preferences": profile_preferences,
            "default_preferences": tv_default_preferences,
            "preference_source": profile_preference_source,
            "discovery_strategy": {
                "media_type": "tv",
                "title_fetching": "frontend",
                "content_sources": tv_sources,
                "discovery_priorities": [
                    "profile_genres",
                    "profile_keywords",
                    "platform_networks",
                    "popular",
                    "top_rated",
                    "new_releases",
                ],
                "recommended_queries": tv_queries,
            },
        },

        "cartoons": {
            "profile_preferences": profile_preferences,
            "default_preferences": cartoon_default_preferences,
            "preference_source": cartoon_preference_source,
            "discovery_strategy": {
                "media_types": ["movie", "tv"],
                "title_fetching": "frontend",
                "content_sources": cartoon_sources,
                "mandatory_genre_filters": {
                    "movie": [16, 10751],
                    "tv": [16, 10751],
                },
                "discovery_priorities": [
                    "mandatory_cartoon_genres",
                    "profile_preferences",
                    "platform_watch_providers",
                    "popular",
                    "top_rated",
                ],
                "recommended_queries": (
                    cartoon_movie_queries + cartoon_tv_queries
                ),
            },
        },
    }


def get_unified_candidate_pool(
    db: Session,
    tmdb: TMDBClient,
    platforms: list[StreamingPlatform],
    profile: Profile,
    movie_limit: int = 100,
    tv_limit: int = 100,
) -> dict:
    """
    Fetch a reusable collection of movies and TV shows
    across all platforms included in the user's subscription.

    This function performs discovery once per media type,
    rather than once for every home-page slider.
    """

    if not platforms:
        return {
            "movies": [],
            "tv_shows": [],
        }

    # -------------------------------------------------
    # 1. Fetch movie candidates across entitled platforms.
    # -------------------------------------------------

    movies = _unified_discovery_collection(
        db=db,
        tmdb=tmdb,
        platforms=platforms,
        profile=profile,
        media_types=["movie"],
        strategy="popular",
        page_size=movie_limit,
    )

    # -------------------------------------------------
    # 2. Fetch TV show candidates across entitled platforms.
    # -------------------------------------------------

    tv_shows = _unified_discovery_collection(
        db=db,
        tmdb=tmdb,
        platforms=platforms,
        profile=profile,
        media_types=["tv"],
        strategy="popular",
        page_size=tv_limit,
    )

    # -------------------------------------------------
    # 3. Return the centralized candidate collection.
    # -------------------------------------------------

    return {
        "movies": [
            {**item, "media_type": "movie"}
            for item in movies
        ],
        "tv_shows": [
            {**item, "media_type": "tv"}
            for item in tv_shows
        ],
    }


def build_collection_from_candidates(
    candidate_pool: dict,
    profile: Profile,
    media_types: list[str],
    genre_ids: list[int] | None = None,
    overrides: dict | None = None,
    strategy: str = "popular",
    page_size: int = 20,
) -> list[dict]:
    """
    Build a content collection from an existing candidate pool.

    No TMDB requests are performed here.
    """

    genre_ids = genre_ids or []
    overrides = overrides or {}

    # -------------------------------------------------
    # 1. Combine the requested media types.
    # -------------------------------------------------

    candidates = []

    if "movie" in media_types:
        candidates.extend(candidate_pool.get("movies", []))

    if "tv" in media_types:
        candidates.extend(candidate_pool.get("tv_shows", []))

    # -------------------------------------------------
    # 2. Apply genre filtering.
    # -------------------------------------------------

    results = []

    for item in candidates:

        item_genres = {
            int(value)
            for value in item.get("genre_ids", [])
            if str(value).isdigit()
        }

        if genre_ids and not item_genres.intersection(
            set(genre_ids)
        ):
            continue

        # -------------------------------------------------
        # 3. Apply minimum vote-count filtering.
        # -------------------------------------------------

        minimum_votes = overrides.get("vote_count.gte")

        if minimum_votes is not None:
            if item.get("vote_count", 0) < minimum_votes:
                continue

        # -------------------------------------------------
        # 4. Apply release-date filtering.
        # -------------------------------------------------

        release_date = item.get("release_date") or ""

        if item.get("media_type") == "movie":
            date_from = overrides.get(
                "primary_release_date.gte"
            )
            date_to = overrides.get(
                "primary_release_date.lte"
            )
        else:
            date_from = overrides.get(
                "first_air_date.gte"
            )
            date_to = overrides.get(
                "first_air_date.lte"
            )

        if date_from and release_date < date_from:
            continue

        if date_to and release_date > date_to:
            continue

        results.append(item)

    # -------------------------------------------------
    # 5. Apply recommendation ranking.
    # -------------------------------------------------

    if strategy == "top_picks":

        preferences = profile.preferences or {}

        preferred_genres = {
            int(value)
            for value in preferences.get(
                "preferred_genres", []
            )
            if str(value).isdigit()
        }

        results.sort(
            key=lambda item: _recommendation_score(
                item,
                preferred_genres,
            ),
            reverse=True,
        )

    # -------------------------------------------------
    # 6. Apply newest-release ranking.
    # -------------------------------------------------

    elif strategy in {
        "newest",
        "recent",
        "latest",
        "new_releases",
    }:

        results.sort(
            key=lambda item: item.get("release_date") or "",
            reverse=True,
        )

    # -------------------------------------------------
    # 7. Default to popularity ranking.
    # -------------------------------------------------

    else:

        results.sort(
            key=lambda item: item.get("popularity", 0),
            reverse=True,
        )

    return results[:page_size]

def get_platform_home(
    db: Session,
    platform_id: UUID,
    profile: Profile,
) -> dict:
    platform = db.get(StreamingPlatform, platform_id)

    if platform is None or not platform.is_active:
        raise HTTPException(
            status_code=404,
            detail="Platform not found or inactive.",
        )

    config = db.scalar(
        select(PlatformProfile).where(
            PlatformProfile.platform_id == platform_id
        )
    )

    if config is None or not config.enabled:
        raise HTTPException(
            status_code=400,
            detail="Platform content configuration is disabled or missing.",
        )

    region_code = config.region_code or settings.tmdb_region
    language = config.language or settings.tmdb_language

    provider_ids = _get_provider_ids(
        db,
        platform_id,
        region_code,
    )

    companies = db.scalars(
        select(PlatformCompany).where(
            PlatformCompany.platform_id == platform_id,
            PlatformCompany.include_in_discovery.is_(True),
        )
    ).all()

    networks = db.scalars(
        select(PlatformNetwork).where(
            PlatformNetwork.platform_id == platform_id,
            PlatformNetwork.include_in_discovery.is_(True),
        )
    ).all()

    sliders = db.scalars(
        select(SliderDefinition)
        .where(
            SliderDefinition.platform_id == platform_id,
            SliderDefinition.enabled.is_(True),
        )
        .order_by(SliderDefinition.display_order)
    ).all()

    preferences = profile.preferences or {}
    preferred_genres = {
        int(value)
        for value in preferences.get("preferred_genres", [])
        if str(value).isdigit()
    }

    company_ids = list({
        company.tmdb_company_id
        for company in companies
        if company.tmdb_company_id
    })

    network_ids = list({
        network.tmdb_network_id
        for network in networks
        if network.tmdb_network_id
    })

    home_sliders = []

    with TMDBClient() as tmdb:
        continue_results = _get_continue_watching_results(
            db=db,
            tmdb=tmdb,
            platform=platform,
            profile=profile,
        )

        # Continue Watching must appear before the discovery sliders.
        if continue_results:
            home_sliders.append({
                "key": "continue_watching",
                "title": f"Continue Watching on {platform.name}",
                "strategy": "continue_watching",
                "media_scope": "mixed",
                "results": continue_results,
            })

        for slider in sliders:
            if slider.media_scope == "movies":
                media_types = (
                    ["movie"] if platform.supports_movies else []
                )
            elif slider.media_scope == "tv_shows":
                media_types = (
                    ["tv"] if platform.supports_tv_shows else []
                )
            else:
                media_types = []
                if platform.supports_movies:
                    media_types.append("movie")
                if platform.supports_tv_shows:
                    media_types.append("tv")

            candidates = {}

            for media_type in media_types:
                endpoint = (
                    "/discover/movie"
                    if media_type == "movie"
                    else "/discover/tv"
                )

                # Main source: provider-filtered discovery.
                results = _fetch_discovery(
                    tmdb=tmdb,
                    endpoint=endpoint,
                    media_type=media_type,
                    provider_ids=provider_ids,
                    region_code=region_code,
                    language=language,
                    page_size=slider.page_size,
                    strategy=slider.strategy,
                    genre_ids=slider.genre_ids or [],
                    overrides=slider.query_overrides or {},
                )

                for item in results:
                    if media_type == "tv" and "name" not in item:
                        continue

                    if media_type == "movie" and "title" not in item:
                        continue

                    candidates[(media_type, item["id"])] = item

                # Supplementary source: mapped companies. Keep the
                # watch-provider filter in place to avoid adding titles
                # solely because a company produced them.

                if company_ids:
                    company_results = _fetch_discovery(
                        tmdb=tmdb,
                        endpoint=endpoint,
                        media_type=media_type,
                        provider_ids=provider_ids,
                        region_code=region_code,
                        language=language,
                        page_size=slider.page_size,
                        strategy=slider.strategy,
                        genre_ids=slider.genre_ids or [],
                        overrides=slider.query_overrides or {},
                        company_ids=company_ids,
                    )

                    for item in company_results:
                        candidates[(media_type, item["id"])] = item

                # TV networks are only applicable to TV discovery.
                if media_type == "tv" and networks:
                    network_results = _fetch_discovery(
                        tmdb=tmdb,
                        endpoint=endpoint,
                        media_type=media_type,
                        provider_ids=provider_ids,
                        region_code=region_code,
                        language=language,
                        page_size=slider.page_size,
                        strategy=slider.strategy,
                        genre_ids=slider.genre_ids or [],
                        overrides=slider.query_overrides or {},
                        network_ids=network_ids,
                    )

                    for item in network_results:
                        candidates[(media_type, item["id"])] = item

            normalized = []

            for (media_type, _), item in candidates.items():
                if not _is_allowed_for_profile(item, profile):
                    continue

                title = _normalise_title(item, media_type)
                normalized.append(title)

            # Randomise the filtered candidate pool on each request.
        
            if slider.strategy == "top_picks":
                normalized.sort(
                    key=lambda item: _recommendation_score(
                        item,
                        preferred_genres,
                    ),
                    reverse=True,
                )

            elif slider.strategy in {
                "newest",
                "recent",
                "latest",
                "new_releases",
            }:
                normalized.sort(
                    key=lambda item: item.get("release_date") or "",
                    reverse=True,
                )

            else:
                normalized.sort(
                    key=lambda item: item.get("popularity", 0),
                    reverse=True,
                )

            home_sliders.append({
                "key": slider.key,
                "title": slider.title,
                "strategy": slider.strategy,
                "media_scope": slider.media_scope,
                "results": normalized[:slider.page_size],
            })

    return {
        "platform": {
            "id": str(platform.id),
            "name": platform.name,
            "slug": platform.slug,
            "icon": platform.icon if platform.icon else None,
        },
        "user": {
            "profile_id": str(profile.id),
            "name": profile.name,
            "avatar_url": profile.avatar_key,
            "account_type": (
                "Kids" if profile.is_kids_profile else "Adult"
            ),
        },
        "region": region_code,
        "language": language,
        "sliders": home_sliders,
    }