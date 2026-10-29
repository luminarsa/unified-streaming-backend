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
) -> list[dict]:
    params = {
        "watch_region": region_code,
        "with_watch_providers": "|".join(
            str(value) for value in provider_ids
        ),
        "include_adult": "false",
        "include_video": "false",
        "language": language,
        "sort_by": _strategy_sort(strategy, media_type),
    }

    if genre_ids:
        params["with_genres"] = "|".join(
            str(value) for value in genre_ids
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
            str(value) for value in company_ids
        )

    if network_ids and media_type == "tv":
        params["with_networks"] = "|".join(
            str(value) for value in network_ids
        )

    # Configuration cannot override provider, region, or adult filters.
    for key, value in (overrides or {}).items():
        if key in ALLOWED_OVERRIDES and value is not None:
            params[key] = value

    # Build a larger pool than the number displayed in the slider.
    # TMDB returns up to 20 discovery results per page.
    candidate_target = max(1, min(page_size, 40))
    pages_to_fetch = (candidate_target + 19) // 20

    results_by_id = {}

    for page_number in range(1, pages_to_fetch + 1):
        page_params = {
            **params,
            "page": page_number,
        }

        data = tmdb.get(endpoint, params=page_params)
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

    return list(results_by_id.values())

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
    provider IDs. Make one discovery flow per media type and
    regional/language group rather than one per platform.

    Shared results are not assigned a false per-title
    available_on attribution. Exact availability requires
    provider verification.
    """
    genre_ids = genre_ids or []
    overrides = overrides or {}

    # Load platform configurations in one query.
    platform_ids = [platform.id for platform in platforms]

    if not platform_ids:
        return []

    configs = db.scalars(
        select(PlatformProfile).where(
            PlatformProfile.platform_id.in_(platform_ids)
        )
    ).all()

    config_by_platform = {
        config.platform_id: config for config in configs
    }

    # Group platforms by region and language. TMDB accepts only
    # one watch_region and language per discovery request.
    groups = {}

    for platform in platforms:
        config = config_by_platform.get(platform.id)

        region_code = (
            config.region_code
            if config and config.region_code
            else settings.tmdb_region
        )
        language = (
            config.language
            if config and config.language
            else settings.tmdb_language
        )

        group_key = (region_code, language)

        groups.setdefault(
            group_key,
            {"platforms": [], "provider_ids": set()},
        )["platforms"].append(platform)

    # Load all provider mappings for these platforms in one query.
    provider_rows = db.scalars(
        select(PlatformProvider).where(
            PlatformProvider.platform_id.in_(platform_ids),
            PlatformProvider.provider_kind.in_(
                ["watch_provider", "tmdb_watch_provider"]
            ),
        )
    ).all()

    for provider in provider_rows:
        config = config_by_platform.get(provider.platform_id)
        region_code = (
            config.region_code
            if config and config.region_code
            else settings.tmdb_region
        )

        language = (
            config.language
            if config and config.language
            else settings.tmdb_language
        )

        group = groups[(region_code, language)]

        # Prefer regional mappings. Global mappings are used only
        # if a platform has no mapping for the requested region.
        group.setdefault("regional_by_platform", {}).setdefault(
            provider.platform_id, []
        )
        group.setdefault("global_by_platform", {}).setdefault(
            provider.platform_id, []
        )

        if provider.external_id is None:
            continue

        if provider.region_code == region_code:
            group["regional_by_platform"][provider.platform_id].append(
                (int(provider.external_id), provider.is_primary)
            )
        elif provider.region_code is None:
            group["global_by_platform"][provider.platform_id].append(
                (int(provider.external_id), provider.is_primary)
            )

    merged = {}

    for (region_code, language), group in groups.items():
        provider_ids = set()

        for platform in group["platforms"]:
            regional = group.get(
                "regional_by_platform", {}
            ).get(platform.id, [])

            global_mappings = group.get(
                "global_by_platform", {}
            ).get(platform.id, [])

            candidates = regional or global_mappings
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

        for media_type in media_types:
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

            endpoint = (
                "/discover/movie"
                if media_type == "movie"
                else "/discover/tv"
            )

            effective_overrides = dict(overrides)

            # Do not send movie-only date filters to TV discovery,
            # or TV-only date filters to movie discovery.
            if media_type == "movie":
                effective_overrides.pop("first_air_date.gte", None)
                effective_overrides.pop("first_air_date.lte", None)
            else:
                effective_overrides.pop("primary_release_date.gte", None)
                effective_overrides.pop("primary_release_date.lte", None)

            # The unified endpoint needs only enough results for the
            # requested collection, rather than a large candidate pool.
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

            for item in results:
                if not _is_allowed_for_profile(item, profile):
                    continue

                key = (media_type, int(item["id"]))

                if key not in merged:
                    merged[key] = _normalise_title(item, media_type)

    results = list(merged.values())

    if strategy == "top_picks":
        preferences = profile.preferences or {}
        preferred_genres = {
            int(value)
            for value in preferences.get("preferred_genres", [])
            if str(value).isdigit()
        }

        results.sort(
            key=lambda item: _recommendation_score(
                item, preferred_genres
            ),
            reverse=True,
        )
    elif strategy in {"newest", "recent", "latest", "new_releases"}:
        results.sort(
            key=lambda item: item.get("release_date") or "",
            reverse=True,
        )
    else:
        results.sort(
            key=lambda item: item.get("popularity", 0),
            reverse=True,
        )

    return results[:page_size]

def get_unified_home(
    db: Session,
    account_id: UUID,
    profile: Profile,
) -> dict:
    """
    Return the unified home page, available platforms, live TV,
    shared content sliders, and dedicated content collections.
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
        entitled_platform_ids = set(
            db.scalars(
                select(PlanEntitlement.platform_id).where(
                    PlanEntitlement.plan_id == plan.id
                )
            ).all()
        )

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
    # 3. Return every active platform with access status.
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
            and platform.id in entitled_platform_ids
        )

        platform_availability[platform.id] = is_available

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

    # Only active platforms actually included in the plan are
    # allowed to contribute subscription-based content.
    entitled_platforms = [
        platform
        for platform in platforms
        if platform.id in entitled_platform_ids
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
        channel_is_available = (
            platform_availability.get(channel_platform.id, False)
            and channel_platform.supports_live_tv
            and live_tv_enabled
        )

        platform_id = str(channel_platform.id)

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
            "name": channel.name,
            "logo_url": channel.logo_url,
            "category": channel.category if channel.category else None,
            "is_available": channel_is_available,
            "availability_status": (
                "available"
                if channel_is_available
                else "not_included"
            ),
        })

    live_tv_platforms = list(live_tv_by_platform.values())

    live_tv_channel_count = sum(
        len(platform["channels"])
        for platform in live_tv_platforms
    )

    # -----------------------------------------------------
    # 5. Define the nine shared home sliders.
    # -----------------------------------------------------
    today = date.today()
    week_ago = today - timedelta(days=7)

    shared_definitions = [
        {
            "key": "hero",
            "title": "Hero",
            "media_types": ["movie", "tv"],
            "genres": [],
            "strategy": "popular",
            "overrides": {"vote_count.gte": 50},
            "limit": 10,
        },
        {
            "key": "new_this_week",
            "title": "New This Week",
            "media_types": ["movie", "tv"],
            "genres": [],
            "strategy": "newest",
            "overrides": {
                "primary_release_date.gte": week_ago.isoformat(),
                "primary_release_date.lte": today.isoformat(),
                "first_air_date.gte": week_ago.isoformat(),
                "first_air_date.lte": today.isoformat(),
            },
            "limit": 20,
        },
        {
            "key": "trending_now",
            "title": "Trending Now",
            "media_types": ["movie", "tv"],
            "genres": [],
            "strategy": "popular",
            "overrides": {"vote_count.gte": 20},
            "limit": 20,
        },
        {
            "key": "top_picks_for_you",
            "title": "Top Picks for You",
            "media_types": ["movie", "tv"],
            "genres": [],
            "strategy": "top_picks",
            "overrides": {"vote_count.gte": 10},
            "limit": 20,
        },
        {
            "key": "action",
            "title": "Action",
            "media_types": ["movie", "tv"],
            "genres": [28, 10759],
            "strategy": "popular",
            "overrides": {},
            "limit": 20,
        },
        {
            "key": "comedy",
            "title": "Comedy",
            "media_types": ["movie", "tv"],
            "genres": [35],
            "strategy": "popular",
            "overrides": {},
            "limit": 20,
        },
        {
            "key": "sci_fi",
            "title": "Sci-Fi",
            "media_types": ["movie", "tv"],
            "genres": [878, 10765],
            "strategy": "popular",
            "overrides": {},
            "limit": 20,
        },
        {
            "key": "thrillers",
            "title": "Thrillers",
            "media_types": ["movie"],
            "genres": [53],
            "strategy": "popular",
            "overrides": {},
            "limit": 20,
        },
        {
            "key": "horror",
            "title": "Horror",
            "media_types": ["movie"],
            "genres": [27],
            "strategy": "popular",
            "overrides": {},
            "limit": 20,
        },
    ]

    home_sliders = []
    movies = []
    tv_shows = []
    cartoons = []

    # -----------------------------------------------------
    # 6. Discover content using entitled platform providers.
    # -----------------------------------------------------
    if entitled_platforms:
        with TMDBClient() as tmdb:

            for definition in shared_definitions:
                results = _unified_discovery_collection(
                    db=db,
                    tmdb=tmdb,
                    platforms=entitled_platforms,
                    profile=profile,
                    media_types=definition["media_types"],
                    genre_ids=definition["genres"],
                    overrides=definition["overrides"],
                    strategy=definition["strategy"],
                    page_size=definition["limit"],
                )

                home_sliders.append({
                    "key": definition["key"],
                    "title": definition["title"],
                    "strategy": definition["strategy"],
                    "media_scope": (
                        "movies"
                        if definition["media_types"] == ["movie"]
                        else "mixed"
                    ),
                    "results": results,
                })

            # Dedicated Movies list.
            movies = _unified_discovery_collection(
                db=db,
                tmdb=tmdb,
                platforms=entitled_platforms,
                profile=profile,
                media_types=["movie"],
                strategy="popular",
                page_size=30,
            )

            # Dedicated TV Shows / Series list.
            tv_shows = _unified_discovery_collection(
                db=db,
                tmdb=tmdb,
                platforms=entitled_platforms,
                profile=profile,
                media_types=["tv"],
                strategy="popular",
                page_size=30,
            )

            # Dedicated Cartoons list: animation and family genres.
            cartoons = _unified_discovery_collection(
                db=db,
                tmdb=tmdb,
                platforms=entitled_platforms,
                profile=profile,
                media_types=["movie", "tv"],
                genre_ids=[16, 10751],
                strategy="popular",
                page_size=30,
            )

    # -----------------------------------------------------
    # 7. Add platform-specific collections.
    #    Shared sliders are not duplicated here.
    # -----------------------------------------------------
    shared_keys = {
        item["key"] for item in shared_definitions
    }

    for platform in entitled_platforms:
        try:
            platform_home = get_platform_home(
                db=db,
                platform_id=platform.id,
                profile=profile,
            )
        except HTTPException as exc:
            if exc.status_code in (400, 404):
                continue
            raise

        for slider in platform_home.get("sliders", []):
            slider_key = slider.get("key", "")

            if slider_key in shared_keys:
                continue

            # Make each platform-specific key stable and readable,
            # e.g. netflix_originals or disney_plus_originals.
            safe_slug = platform.slug.replace("-", "_")
            safe_slider_key = slider_key.replace("-", "_")
            public_key = f"{safe_slug}_{safe_slider_key}"

            attributed_results = []

            for result in slider.get("results", []):
                result = dict(result)

                result["available_on"] = [{
                    "platform_id": str(platform.id),
                    "platform_name": platform.name,
                    "platform_slug": platform.slug,
                }]

                attributed_results.append(result)

            home_sliders.append({
                **slider,
                "key": public_key,
                "platform_id": str(platform.id),
                "platform_name": platform.name,
                "results": attributed_results,
            })

    # -----------------------------------------------------
    # 8. Return the complete response.
    # -----------------------------------------------------
    return {
        "home": {
            "sliders": home_sliders,
        },
        "all_platforms": all_platforms,
        "live_tv": {
            "count": live_tv_channel_count,
            "platforms": live_tv_platforms,
        },
        "movies": {
            "count": len(movies),
            "results": movies,
        },
        "tv_shows": {
            "count": len(tv_shows),
            "results": tv_shows,
        },
        "cartoons": {
            "count": len(cartoons),
            "results": cartoons,
        },
    }

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
                company_ids = list({
                    company.tmdb_company_id for company in companies
                })

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
                    network_ids = list({
                        network.tmdb_network_id for network in networks
                    })

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
            random.shuffle(normalized)

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
        },
        "profile": {
            "id": str(profile.id),
            "is_kids_profile": profile.is_kids_profile,
        },
        "region": region_code,
        "language": language,
        "sliders": home_sliders,
        "attribution": "Content metadata provided by TMDB.",
    }