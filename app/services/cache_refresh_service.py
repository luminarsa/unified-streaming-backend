
import logging
import json

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings

from app.models.platform_config import (
    StreamingPlatform,
    PlatformProfile,
    SliderDefinition,
    PlatformCompany,
    PlatformNetwork,
)

from app.services.content import (
    _get_provider_ids,
    _fetch_discovery,
)

from app.services.tmdb_client import TMDBClient


logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# CACHE REFRESH CONFIGURATION DISCOVERY
# ---------------------------------------------------------


def discover_cache_refresh_targets(db: Session) -> list[dict]:
    """
    Discover active platforms with enabled configurations
    and enabled home-page sliders.

    Also loads provider, production company and TV network
    mappings before the long-running TMDB refresh begins.
    """

    platforms = db.scalars(
        select(StreamingPlatform).where(
            StreamingPlatform.is_active.is_(True)
        )
    ).all()

    refresh_targets = []

    for platform in platforms:

        # -------------------------------------------------
        # 1. Load platform configuration
        # -------------------------------------------------

        config = db.scalar(
            select(PlatformProfile).where(
                PlatformProfile.platform_id == platform.id,
                PlatformProfile.enabled.is_(True),
            )
        )

        if config is None:
            continue

        # -------------------------------------------------
        # 2. Load enabled sliders
        # -------------------------------------------------

        sliders = db.scalars(
            select(SliderDefinition)
            .where(
                SliderDefinition.platform_id == platform.id,
                SliderDefinition.enabled.is_(True),
            )
            .order_by(SliderDefinition.display_order)
        ).all()

        if not sliders:
            continue

        region_code = config.region_code or settings.tmdb_region
        language = config.language or settings.tmdb_language

        # -------------------------------------------------
        # 3. Load watch provider IDs
        # -------------------------------------------------

        provider_ids = _get_provider_ids(
            db=db,
            platform_id=platform.id,
            region_code=region_code,
        )

        # -------------------------------------------------
        # 4. Load production company mappings
        # -------------------------------------------------

        companies = db.scalars(
            select(PlatformCompany).where(
                PlatformCompany.platform_id == platform.id,
                PlatformCompany.include_in_discovery.is_(True),
            )
        ).all()

        company_ids = sorted({
            int(company.tmdb_company_id)
            for company in companies
            if company.tmdb_company_id is not None
        })

        # -------------------------------------------------
        # 5. Load TV network mappings
        # -------------------------------------------------

        networks = db.scalars(
            select(PlatformNetwork).where(
                PlatformNetwork.platform_id == platform.id,
                PlatformNetwork.include_in_discovery.is_(True),
            )
        ).all()

        network_ids = sorted({
            int(network.tmdb_network_id)
            for network in networks
            if network.tmdb_network_id is not None
        })

        # -------------------------------------------------
        # 6. Prepare slider configurations
        # -------------------------------------------------

        slider_configs = []

        for slider in sliders:

            if slider.media_scope == "movies":
                requested_types = ["movie"]

            elif slider.media_scope == "tv_shows":
                requested_types = ["tv"]

            else:
                requested_types = ["movie", "tv"]

            media_types = []

            if (
                "movie" in requested_types
                and platform.supports_movies
            ):
                media_types.append("movie")

            if (
                "tv" in requested_types
                and platform.supports_tv_shows
            ):
                media_types.append("tv")

            if not media_types:
                continue

            slider_configs.append({
                "id": str(slider.id),
                "key": slider.key,
                "title": slider.title,
                "strategy": slider.strategy,
                "media_scope": slider.media_scope,
                "media_types": media_types,
                "genre_ids": slider.genre_ids or [],
                "query_overrides": slider.query_overrides or {},
                "page_size": slider.page_size,
                "display_order": slider.display_order,
            })

        if not slider_configs:
            continue

        # -------------------------------------------------
        # 7. Save everything needed for the refresh
        # -------------------------------------------------

        refresh_targets.append({
            "platform_id": str(platform.id),
            "platform_name": platform.name,
            "platform_slug": platform.slug,
            "region_code": region_code,
            "language": language,

            "provider_ids": provider_ids,
            "company_ids": company_ids,
            "network_ids": network_ids,

            "sliders": slider_configs,
        })

    logger.info(
        "CACHE REFRESH DISCOVERY | Platforms discovered=%s",
        len(refresh_targets),
    )

    return refresh_targets

# ---------------------------------------------------------
# DISCOVERY QUERY REFRESH
# ---------------------------------------------------------


def refresh_platform_discovery(
    tmdb: TMDBClient,
    target: dict,
    refreshed_queries: set,
) -> dict:
    """
    Refresh all unique discovery queries for one platform.

    Uses provider, company and network mappings that were
    loaded before the TMDB refresh started.

    Uses the same discovery function and Redis cache keys
    as the normal platform homepage.
    """

    platform_name = target["platform_name"]

    region_code = target["region_code"]
    language = target["language"]

    # -----------------------------------------------------
    # 1. Use preloaded mapping IDs
    # -----------------------------------------------------

    provider_ids = target["provider_ids"]
    company_ids = target["company_ids"]
    network_ids = target["network_ids"]

    logger.info(
        "CACHE REFRESH | Platform=%s | Providers=%s | Companies=%s | Networks=%s",
        platform_name,
        provider_ids,
        company_ids,
        network_ids,
    )

    # -----------------------------------------------------
    # 2. Refresh each enabled slider
    # -----------------------------------------------------

    successful_queries = 0
    skipped_queries = 0
    failed_queries = 0
    refreshed_results = 0

    for slider in target["sliders"]:

        for media_type in slider["media_types"]:

            endpoint = (
                "/discover/movie"
                if media_type == "movie"
                else "/discover/tv"
            )

            # Each slider has three possible discovery sources:
            #
            # 1. Watch providers.
            # 2. Production companies.
            # 3. TV networks (TV only).

            discovery_sources = [
                {
                    "name": "provider",
                    "company_ids": None,
                    "network_ids": None,
                }
            ]

            if company_ids:
                discovery_sources.append({
                    "name": "company",
                    "company_ids": company_ids,
                    "network_ids": None,
                })

            if media_type == "tv" and network_ids:
                discovery_sources.append({
                    "name": "network",
                    "company_ids": None,
                    "network_ids": network_ids,
                })

            for source in discovery_sources:

                # -----------------------------------------
                # Build a unique identity for this query
                # -----------------------------------------

                query_identity = {
                    "endpoint": endpoint,
                    "media_type": media_type,
                    "provider_ids": sorted(provider_ids),
                    "region_code": region_code,
                    "language": language,
                    "page_size": slider["page_size"],
                    "strategy": slider["strategy"],
                    "genre_ids": slider["genre_ids"],
                    "overrides": slider["query_overrides"],
                    "company_ids": source["company_ids"],
                    "network_ids": source["network_ids"],
                    "kids_mode": False,
                }

                query_key = json.dumps(
                    query_identity,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )

                if query_key in refreshed_queries:
                    skipped_queries += 1
                    continue

                refreshed_queries.add(query_key)

                # -----------------------------------------
                # Fetch discovery results from TMDB
                # -----------------------------------------

                try:
                    cache_status = {}

                    results = _fetch_discovery(
                        tmdb=tmdb,
                        endpoint=endpoint,
                        media_type=media_type,
                        provider_ids=provider_ids,
                        region_code=region_code,
                        language=language,
                        page_size=slider["page_size"],
                        strategy=slider["strategy"],
                        genre_ids=slider["genre_ids"],
                        overrides=slider["query_overrides"],
                        company_ids=source["company_ids"],
                        network_ids=source["network_ids"],
                        force_refresh=True,
                        cache_status=cache_status,
                    )

                    if cache_status.get("saved") is True:

                        successful_queries += 1
                        refreshed_results += len(results)

                    else:

                        failed_queries += 1

                        logger.error(
                            "CACHE REFRESH | REDIS WRITE FAILED | "
                            "Platform=%s | Slider=%s | Media=%s | Source=%s",
                            platform_name,
                            slider["key"],
                            media_type,
                            source["name"],
                        )


                    logger.info(
                        "CACHE REFRESH | SUCCESS | Platform=%s | Slider=%s | Media=%s | Source=%s | Results=%s",
                        platform_name,
                        slider["key"],
                        media_type,
                        source["name"],
                        len(results),
                    )

                except Exception:

                    failed_queries += 1

                    logger.exception(
                        "CACHE REFRESH | FAILED | Platform=%s | Slider=%s | Media=%s | Source=%s",
                        platform_name,
                        slider["key"],
                        media_type,
                        source["name"],
                    )

    return {
        "platform": platform_name,
        "successful_queries": successful_queries,
        "skipped_queries": skipped_queries,
        "failed_queries": failed_queries,
        "refreshed_results": refreshed_results,
    }

# ---------------------------------------------------------
# CENTRAL CACHE REFRESH ENTRY POINT
# ---------------------------------------------------------

def refresh_lumina_cache(db: Session) -> dict:
    """
    Central entry point for refreshing Lumina's shared cache.

    1. Discover active platforms and enabled sliders.
    2. Fetch fresh TMDB discovery results.
    3. Save results into the existing Redis cache keys.
    """

    refresh_started_at = datetime.now(timezone.utc)

    logger.info(
        "LUMINA CACHE REFRESH | Process started | time=%s",
        refresh_started_at.isoformat(),
    )

    platform_results = []

    total_successful_queries = 0
    total_skipped_queries = 0
    total_failed_queries = 0
    total_refreshed_results = 0

    try:

        # -------------------------------------------------
        # 1. Discover refresh targets.
        # -------------------------------------------------

        refresh_targets = discover_cache_refresh_targets(db)
        db.rollback()

        logger.info(
            "LUMINA CACHE REFRESH | Targets discovered=%s",
            len(refresh_targets),
        )

        # Keep track of identical queries across platforms
        # and sliders during this refresh run.
        refreshed_queries = set()

        # -------------------------------------------------
        # 2. Connect to TMDB once for the entire refresh.
        # -------------------------------------------------

        with TMDBClient() as tmdb:

            for target in refresh_targets:

                try:

                    result = refresh_platform_discovery(
                        tmdb=tmdb,
                        target=target,
                        refreshed_queries=refreshed_queries,
                    )

                    platform_results.append(result)

                    total_successful_queries += (
                        result["successful_queries"]
                    )

                    total_skipped_queries += (
                        result["skipped_queries"]
                    )

                    total_failed_queries += (
                        result["failed_queries"]
                    )

                    total_refreshed_results += (
                        result["refreshed_results"]
                    )

                except Exception:

                    total_failed_queries += 1

                    logger.exception(
                        "LUMINA CACHE REFRESH | Platform failed | Platform=%s",
                        target["platform_name"],
                    )

                    platform_results.append({
                        "platform": target["platform_name"],
                        "error": "Platform refresh failed.",
                    })


        # -------------------------------------------------
        # 3. Determine overall refresh status
        # -------------------------------------------------

        if total_failed_queries > 0 and total_successful_queries > 0:
            refresh_status = "partial_success"

        elif total_failed_queries > 0:
            refresh_status = "error"

        elif total_successful_queries == 0:
            refresh_status = "no_queries_refreshed"

        else:
            refresh_status = "success"

        refresh_completed_at = datetime.now(timezone.utc)

        logger.info(
            "LUMINA CACHE REFRESH | Completed | "
            "Status=%s | Successful=%s | Failed=%s | "
            "Skipped=%s | Results=%s",
            refresh_status,
            total_successful_queries,
            total_failed_queries,
            total_skipped_queries,
            total_refreshed_results,
        )

        return {
            "status": refresh_status,
            "platform_count": len(refresh_targets),
            "successful_queries": total_successful_queries,
            "failed_queries": total_failed_queries,
            "skipped_queries": total_skipped_queries,
            "refreshed_results": total_refreshed_results,
            "platforms": platform_results,
            "started_at": refresh_started_at.isoformat(),
            "completed_at": refresh_completed_at.isoformat(),
        }


    except Exception:

        logger.exception(
            "LUMINA CACHE REFRESH | Process failed."
        )

        return {
            "status": "error",
            "message": "Lumina cache refresh failed.",
            "started_at": refresh_started_at.isoformat(),
        }
