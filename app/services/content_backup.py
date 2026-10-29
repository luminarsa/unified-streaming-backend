from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from datetime import datetime, timedelta, timezone
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
        "with_watch_providers": ",".join(
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
    candidate_target = min(60, max(40, page_size * 2))
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

def get_unified_home(
    db: Session,
    account_id: UUID,
    profile: Profile,
) -> dict:
    """
    Return the unified home page, available platforms,
    and live TV channels for an account.
    """

    # 1. Find the most recent subscription that grants access.
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

    # 2. Determine which platforms the plan includes.
    entitled_platform_ids = set()
    live_tv_enabled = False

    if subscription is not None and plan is not None:
        entitled_platform_ids = set(
            db.scalars(
                select(PlanEntitlement.platform_id)
                .where(PlanEntitlement.plan_id == plan.id)
            ).all()
        )

        live_tv_enabled = db.scalar(
            select(PlanFeature.is_enabled).where(
                PlanFeature.plan_id == plan.id,
                PlanFeature.feature_code == "live_tv",
            )
        ) is True

    # 3. Return all active streaming platforms, including
    # platforms that are not included in the subscription.
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

    # 4. Load every active live-TV channel.
    # For now, return all channels, but calculate their availability
    # using the subscription's platform and live-TV entitlements.
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
            PlatformLiveChannel.display_order.asc(),
            PlatformLiveChannel.name.asc(),
        )
    ).all()

    live_tv_channels = []

    for channel, channel_platform in channel_rows:
        channel_is_available = (
            platform_availability.get(channel_platform.id, False)
            and channel_platform.supports_live_tv
            and live_tv_enabled
        )

        live_tv_channels.append({
            "id": str(channel.id),
            "name": channel.name,
            "logo_url": channel.logo_url,
            "platform_id": str(channel_platform.id),
            "platform_name": channel_platform.name,
            "is_available": channel_is_available,
            "availability_status": (
                "available"
                if channel_is_available
                else "not_included"
            ),
        })

    # 5. Retrieve content from the platforms included in the plan.
    #
    # Shared slider keys are merged. Platform-specific collections
    # are kept separate so, for example, Netflix Originals and
    # Disney+ Originals do not get mixed together.
    shared_slider_order = [
        "hero",
        "new_this_week",
        "trending_now",
        "top_picks_for_you",
        "action",
        "comedy",
        "sci_fi",
        "thrillers",
        "horror",
    ]

    shared_slider_titles = {
        "hero": "Featured",
        "new_this_week": "New This Week",
        "trending_now": "Trending Now",
        "top_picks_for_you": "Top Picks for You",
        "action": "Action",
        "comedy": "Comedy",
        "sci_fi": "Sci-Fi",
        "thrillers": "Thrillers",
        "horror": "Horror",
    }

    shared_sliders = {}
    platform_sliders = []

    for platform in platforms:
        if platform.id not in entitled_platform_ids:
            continue

        try:
            platform_home = get_platform_home(
                db=db,
                platform_id=platform.id,
                profile=profile,
            )
        except HTTPException as exc:
            # Skip a platform whose content configuration is missing
            # or disabled. Re-raise other errors.
            if exc.status_code in (400, 404):
                continue
            raise

        for slider in platform_home.get("sliders", []):
            slider_key = slider.get("key", "")

            if slider_key in shared_slider_order:
                if slider_key not in shared_sliders:
                    shared_sliders[slider_key] = {
                        "key": slider_key,
                        "title": shared_slider_titles.get(
                            slider_key,
                            slider.get("title", slider_key),
                        ),
                        "strategy": slider.get("strategy"),
                        "media_scope": slider.get("media_scope"),
                        "results": [],
                        "_seen": set(),
                    }

                destination = shared_sliders[slider_key]

                for item in slider.get("results", []):
                    media_type = item.get("media_type", "unknown")
                    media_id = item.get("id")

                    # Avoid adding the same movie or show twice
                    # to the same shared slider.
                    identity = (media_type, str(media_id))

                    if identity not in destination["_seen"]:
                        destination["_seen"].add(identity)
                        destination["results"].append(item)

            else:
                # Keep Continue Watching and platform-specific
                # collections separate.
                platform_sliders.append({
                    **slider,
                    "key": f"{platform.slug}:{slider_key}",
                    "platform_id": str(platform.id),
                    "platform_name": platform.name,
                })

    home_sliders = []

    for slider_key in shared_slider_order:
        slider = shared_sliders.get(slider_key)

        if slider is not None:
            slider.pop("_seen", None)
            home_sliders.append(slider)

    home_sliders.extend(platform_sliders)

    # 6. Return the complete unified home response.
    return {
        "home": {
            "sliders": home_sliders,
        },
        "all_platforms": all_platforms,
        "live_tv": {
            "count": len(live_tv_channels),
            "channels": live_tv_channels,
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