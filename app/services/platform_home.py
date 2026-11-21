
import asyncio
import logging

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import HTTPException

from app.models.identity import Profile

from app.models.platform_config import (
    StreamingPlatform,
    PlatformProfile,
    PlatformProvider,
    PlatformCompany,
    PlatformNetwork,
    SliderDefinition,
    SliderCuratedTitle,
    SliderKeyword,
    SliderCollection,
    SliderCompany,
    SliderNetwork,
    SliderExcludedTitle,
)

from app.services.tmdb import TMDBClient
from app.services.tmdb_client import TMDBClient as SyncTMDBClient


logger = logging.getLogger(__name__)

IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

KIDS_DISCOVERY_GENRE_IDS = {16, 10751}

PROTECTED_QUERY_PARAMETERS = {
    "page",
    "include_adult",
    "language",
    "region",
    "watch_region",
    "with_watch_providers",
    "with_watch_monetization_types",
}


class PlatformHomeService:

    def __init__(self, tmdb: TMDBClient | None = None):
        self.tmdb = tmdb or TMDBClient()

    # ==================================================
    # LOAD PLATFORM CONFIGURATION
    # ==================================================

    def _load_config(self, db: Session, platform_id: UUID):

        platform = db.scalar(
            select(StreamingPlatform).where(
                StreamingPlatform.id == platform_id,
                StreamingPlatform.is_active.is_(True),
            )
        )

        if not platform:
            raise HTTPException(
                status_code=404,
                detail="Platform not found or inactive.",
            )

        platform_profile = db.scalar(
            select(PlatformProfile).where(
                PlatformProfile.platform_id == platform.id,
                PlatformProfile.enabled.is_(True),
            )
        )

        if not platform_profile:
            raise HTTPException(
                status_code=400,
                detail="Platform content configuration is disabled or missing.",
            )

        sliders = db.scalars(
            select(SliderDefinition)
            .where(
                SliderDefinition.platform_id == platform.id,
                SliderDefinition.enabled.is_(True),
            )
            .order_by(SliderDefinition.display_order)
        ).all()

        slider_ids = [slider.id for slider in sliders]

        providers = db.scalars(
            select(PlatformProvider).where(
                PlatformProvider.platform_id == platform.id,
            )
        ).all()

        # Platform-wide production companies.
        platform_companies = db.scalars(
            select(PlatformCompany).where(
                PlatformCompany.platform_id == platform.id,
                PlatformCompany.include_in_discovery.is_(True),
            )
        ).all()

        # Platform-wide television networks.
        platform_networks = db.scalars(
            select(PlatformNetwork).where(
                PlatformNetwork.platform_id == platform.id,
                PlatformNetwork.include_in_discovery.is_(True),
            )
        ).all()

        config = {
            slider_id: {
                "curated_titles": [],
                "keywords": [],
                "collections": [],
                "companies": [],
                "networks": [],
                "excluded_titles": [],
            }
            for slider_id in slider_ids
        }

        if slider_ids:

            model_groups = [
                ("curated_titles", SliderCuratedTitle),
                ("keywords", SliderKeyword),
                ("collections", SliderCollection),
                ("companies", SliderCompany),
                ("networks", SliderNetwork),
                ("excluded_titles", SliderExcludedTitle),
            ]

            for group_name, model in model_groups:

                records = db.scalars(
                    select(model).where(
                        model.slider_id.in_(slider_ids),
                        model.enabled.is_(True),
                    )
                ).all()

                for record in records:
                    config[record.slider_id][group_name].append(record)

        logger.info(
            "Loaded platform home configuration: "
            "platform=%s providers=%s networks=%s companies=%s sliders=%s",
            platform.name,
            len(providers),
            len(platform_networks),
            len(platform_companies),
            len(sliders),
        )

        return (
            platform,
            platform_profile,
            sliders,
            providers,
            platform_networks,
            platform_companies,
            config,
        )

    # ==================================================
    # PROFILE FILTERING
    # ==================================================

    def _get_genre_ids(self, item: dict) -> set[int]:

        values = item.get("genre_ids") or []

        if not values and item.get("genres"):
            values = item.get("genres", [])

        genre_ids = set()

        for value in values:

            try:
                if isinstance(value, dict):
                    value = value.get("id")

                genre_id = int(value)

                if genre_id > 0:
                    genre_ids.add(genre_id)

            except (TypeError, ValueError):
                continue

        return genre_ids

    def _allowed_for_profile(
        self,
        item: dict,
        profile: Profile,
    ) -> bool:

        if item.get("adult", False):
            return False

        if not profile.is_kids_profile:
            return True

        genre_ids = self._get_genre_ids(item)

        return bool(
            genre_ids & KIDS_DISCOVERY_GENRE_IDS
        )

    # ==================================================
    # NORMALIZE TMDB TITLE
    # ==================================================

    def _normalize_title(
        self,
        item: dict,
        media_type: str,
    ) -> dict:

        is_movie = media_type == "movie"

        poster_path = item.get("poster_path")
        backdrop_path = item.get("backdrop_path")

        return {
            "tmdb_id": item["id"],
            "media_type": media_type,
            "title": (
                item.get("title")
                if is_movie
                else item.get("name")
            ) or "Untitled",
            "overview": item.get("overview") or "",
            "release_date": (
                item.get("release_date")
                if is_movie
                else item.get("first_air_date")
            ),
            "genre_ids": sorted(
                self._get_genre_ids(item)
            ),
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
            "popularity": float(
                item.get("popularity") or 0
            ),
            "vote_average": float(
                item.get("vote_average") or 0
            ),
            "vote_count": int(
                item.get("vote_count") or 0
            ),
            "adult": bool(
                item.get("adult", False)
            ),
        }

    # ==================================================
    # CLEAN TMDB IDS
    # ==================================================

    def _clean_ids(self, values) -> list[int]:

        result = []

        for value in values:

            try:
                value = int(value)

                if value > 0 and value not in result:
                    result.append(value)

            except (TypeError, ValueError):
                continue

        return result

    # ==================================================
    # GET SORT ORDER
    # ==================================================

    def _get_sort_order(
        self,
        strategy: str,
        media_type: str,
    ) -> str:

        if strategy in {
            "provider_recent",
            "company_recent",
            "network_recent",
            "recent",
            "latest",
            "newest",
            "new_releases",
        }:
            return (
                "primary_release_date.desc"
                if media_type == "movie"
                else "first_air_date.desc"
            )

        if strategy in {
            "top_rated",
            "highest_rated",
        }:
            return "vote_average.desc"

        return "popularity.desc"

    # ==================================================
    # APPLY SAFE QUERY OVERRIDES
    # ==================================================

    def _apply_overrides(
        self,
        params: dict,
        overrides: dict,
    ) -> None:

        for key, value in (overrides or {}).items():

            if key in PROTECTED_QUERY_PARAMETERS:
                continue

            if value is None:
                continue

            if isinstance(value, (str, int, float, bool)):
                params[key] = value

            elif isinstance(value, list):
                params[key] = "|".join(
                    str(item) for item in value
                )

    # ==================================================
    # CHECK ACTUAL PLATFORM SUBSCRIPTION AVAILABILITY
    # ==================================================

    async def _has_subscription_availability(
        self,
        tmdb_id: int,
        media_type: str,
        region: str,
        provider_ids: list[int],
        availability_cache: dict,
    ) -> bool:

        if not provider_ids:
            return False

        cache_key = (
            media_type,
            tmdb_id,
            region,
        )

        if cache_key in availability_cache:
            return availability_cache[cache_key]

        try:
            provider_data = await self.tmdb.content_watch_providers(
                media_type,
                tmdb_id,
            )

            available = any(
                self.tmdb.is_available_on_provider(
                    provider_data=provider_data,
                    provider_id=provider_id,
                    region=region,
                    monetization_types=("flatrate",),
                )
                for provider_id in provider_ids
            )

            availability_cache[cache_key] = available

            return available

        except Exception as exc:

            logger.warning(
                "Could not verify subscription availability: "
                "media_type=%s tmdb_id=%s region=%s error=%s",
                media_type,
                tmdb_id,
                region,
                str(exc),
            )

            availability_cache[cache_key] = False

            return False

    # ==================================================
    # FETCH COLLECTION CONTENT
    # ==================================================

    async def _get_collection_titles(
        self,
        collection_id: int,
        language: str,
    ) -> list[dict]:

        try:
            payload = await self.tmdb.get(
                f"/collection/{collection_id}",
                params={"language": language},
            )

            return payload.get("parts", [])

        except Exception as exc:

            logger.warning(
                "Collection discovery failed: collection=%s error=%s",
                collection_id,
                str(exc),
            )

            return []

    # ==================================================
    # FETCH CURATED TITLE
    # ==================================================

    async def _get_curated_title(
        self,
        tmdb_id: int,
        media_type: str,
        language: str,
    ) -> dict | None:

        try:
            return await self.tmdb.content_details(
                media_type,
                tmdb_id,
            )

        except Exception as exc:

            logger.warning(
                "Curated title lookup failed: title=%s error=%s",
                tmdb_id,
                str(exc),
            )

            return None

    # ==================================================
    # RUN ONE INDEPENDENT DISCOVERY QUERY
    # ==================================================

    async def _run_discovery_query(
        self,
        row,
        media_type: str,
        source_name: str,
        source_ids: list[int],
        region: str,
        language: str,
        page: int,
        keyword_ids: list[int],
        strategy: str,
    ):

        if not source_ids:
            return None

        params = {
            "page": page,
            "include_adult": "false",
            "language": language,
            "sort_by": self._get_sort_order(
                strategy,
                media_type,
            ),
        }

        # Every source gets its own independent TMDB filter.
        if source_name == "provider":

            params["with_watch_providers"] = "|".join(
                str(value) for value in source_ids
            )

            params["watch_region"] = region
            params["with_watch_monetization_types"] = "flatrate"

            if media_type == "movie":
                params["region"] = region

        elif source_name == "network":

            params["with_networks"] = "|".join(
                str(value) for value in source_ids
            )

        elif source_name == "company":

            params["with_companies"] = "|".join(
                str(value) for value in source_ids
            )

        genre_ids = self._clean_ids(
            row.genre_ids or []
        )

        if genre_ids:
            params["with_genres"] = "|".join(
                str(value) for value in genre_ids
            )

        if keyword_ids:
            params["with_keywords"] = "|".join(
                str(value) for value in keyword_ids
            )

        if strategy in {
            "top_rated",
            "highest_rated",
        }:
            params["vote_count.gte"] = 100

        if strategy.endswith("_recent") or strategy in {
            "recent",
            "latest",
            "newest",
            "new_releases",
        }:

            date_field = (
                "primary_release_date.lte"
                if media_type == "movie"
                else "first_air_date.lte"
            )

            params[date_field] = date.today().isoformat()

        # Apply ordinary slider overrides first.
        self._apply_overrides(
            params,
            row.query_overrides or {},
        )

        # Reapply the source filter after overrides so that
        # provider, network and company discovery stay independent.
        if source_name == "provider":

            params["with_watch_providers"] = "|".join(
                str(value) for value in source_ids
            )

            params["watch_region"] = region
            params["with_watch_monetization_types"] = "flatrate"

        elif source_name == "network":

            params["with_networks"] = "|".join(
                str(value) for value in source_ids
            )

        elif source_name == "company":

            params["with_companies"] = "|".join(
                str(value) for value in source_ids
            )

        try:
            return await self.tmdb.discover(
                media_type,
                params,
            )

        except Exception as exc:

            logger.warning(
                "Platform discovery query failed: "
                "slider=%s source=%s media_type=%s error=%s",
                row.key,
                source_name,
                media_type,
                str(exc),
            )

            return None

    # ==================================================
    # QUERY ONE SLIDER
    # ==================================================

    async def _query_row(
        self,
        row,
        viewer_profile: Profile,
        platform_profile: PlatformProfile,
        providers,
        platform_networks,
        platform_companies,
        slider_config: dict,
        supported_media_types: list[str],
        availability_cache: dict,
        page: int = 1,
    ):

        region = (
            platform_profile.region_code or "US"
        ).strip().upper()

        language = (
            platform_profile.language or "en-US"
        )

        strategy = (
            row.strategy or ""
        ).strip().lower()

        slider_media_types = {
            "mixed": ["movie", "tv"],
            "movies": ["movie"],
            "tv_shows": ["tv"],
        }.get(row.media_scope, [])

        media_types = [
            media_type
            for media_type in slider_media_types
            if media_type in supported_media_types
        ]

        if not media_types:
            return [], False

        # --------------------------------------------------
        # COLLECT ALL PLATFORM WATCH PROVIDER IDS
        # --------------------------------------------------

        provider_ids = self._clean_ids([
            provider.external_id
            for provider in providers
            if provider.provider_kind == "watch_provider"
            and (
                not provider.region_code
                or provider.region_code.strip().upper() == region
            )
        ])

        # --------------------------------------------------
        # COLLECT ALL PLATFORM NETWORK IDS
        # PLUS SLIDER-SPECIFIC NETWORK IDS
        # --------------------------------------------------

        network_values = [
            item.tmdb_network_id
            for item in platform_networks
        ]

        network_values.extend([
            item.tmdb_network_id
            for item in slider_config["networks"]
        ])

        network_ids = self._clean_ids(network_values)

        # --------------------------------------------------
        # COLLECT ALL PLATFORM COMPANY IDS
        # PLUS SLIDER-SPECIFIC COMPANY IDS
        # --------------------------------------------------

        company_values = [
            item.tmdb_company_id
            for item in platform_companies
        ]

        company_values.extend([
            item.tmdb_company_id
            for item in slider_config["companies"]
        ])

        # Preserve existing company-specific query overrides.
        override_companies = (
            row.query_overrides or {}
        ).get("with_companies", [])

        if not isinstance(override_companies, list):
            override_companies = str(
                override_companies
            ).replace(",", "|").split("|")

        company_values.extend(override_companies)

        network_values_override = (
            row.query_overrides or {}
        ).get("with_networks", [])

        if not isinstance(network_values_override, list):
            network_values_override = str(
                network_values_override
            ).replace(",", "|").split("|")

        network_values.extend(network_values_override)

        company_ids = self._clean_ids(company_values)
        network_ids = self._clean_ids(network_values)

        # Network discovery is for television content.
        if strategy.startswith("network_"):
            media_types = [
                media_type
                for media_type in media_types
                if media_type == "tv"
            ]

        excluded = {
            (item.tmdb_id, item.media_type)
            for item in slider_config["excluded_titles"]
        }

        # Each candidate stores:
        # item, media_type, is_curated, source_priority
        #
        # Priority:
        # 0 = curated / provider / collection
        # 1 = network
        # 2 = company
        candidates = {}

        boosted_keys = set()
        has_more = False

        # --------------------------------------------------
        # 1. CURATED TITLES
        # --------------------------------------------------

        curated = sorted(
            slider_config["curated_titles"],
            key=lambda item: item.priority,
        )

        for curated_item in curated:

            if curated_item.media_type not in media_types:
                continue

            key = (
                curated_item.tmdb_id,
                curated_item.media_type,
            )

            if key in excluded:
                continue

            item = await self._get_curated_title(
                curated_item.tmdb_id,
                curated_item.media_type,
                language,
            )

            if not item:
                continue

            available = await self._has_subscription_availability(
                tmdb_id=curated_item.tmdb_id,
                media_type=curated_item.media_type,
                region=region,
                provider_ids=provider_ids,
                availability_cache=availability_cache,
            )

            if not available:
                continue

            candidates[key] = (
                item,
                curated_item.media_type,
                True,
                0,
            )

        # --------------------------------------------------
        # 2. COLLECTION TITLES
        # --------------------------------------------------

        collections = sorted(
            slider_config["collections"],
            key=lambda item: item.priority,
        )

        for collection in collections:

            collection_items = await self._get_collection_titles(
                collection.tmdb_collection_id,
                language,
            )

            for item in collection_items:

                media_type = "movie"

                if media_type not in media_types:
                    continue

                tmdb_id = item.get("id")

                if not tmdb_id:
                    continue

                key = (tmdb_id, media_type)

                if key in excluded or key in candidates:
                    continue

                available = await self._has_subscription_availability(
                    tmdb_id=tmdb_id,
                    media_type=media_type,
                    region=region,
                    provider_ids=provider_ids,
                    availability_cache=availability_cache,
                )

                if not available:
                    continue

                candidates[key] = (
                    item,
                    media_type,
                    False,
                    0,
                )

        # --------------------------------------------------
        # 3. GET KEYWORD CONFIGURATION
        # --------------------------------------------------

        include_keyword_ids = self._clean_ids([
            item.tmdb_keyword_id
            for item in slider_config["keywords"]
            if item.match_type == "include"
        ])

        boost_keyword_ids = self._clean_ids([
            item.tmdb_keyword_id
            for item in slider_config["keywords"]
            if item.match_type == "boost"
        ])

        # --------------------------------------------------
        # 4. BUILD ALL INDEPENDENT DISCOVERY TASKS
        #
        # Provider queries first.
        # Network queries second.
        # Company queries third.
        #
        # asyncio.gather executes them concurrently.
        # --------------------------------------------------

        discovery_sources = [
            ("provider", provider_ids, 0),
            ("network", network_ids, 1),
            ("company", company_ids, 2),
        ]

        discovery_tasks = []

        for media_type in media_types:

            for source_name, source_ids, source_priority in discovery_sources:

                if not source_ids:
                    continue

                # Base discovery query.
                discovery_tasks.append({
                    "source": source_name,
                    "media_type": media_type,
                    "priority": source_priority,
                    "is_boost": False,
                    "task": self._run_discovery_query(
                        row=row,
                        media_type=media_type,
                        source_name=source_name,
                        source_ids=source_ids,
                        region=region,
                        language=language,
                        page=page,
                        keyword_ids=include_keyword_ids,
                        strategy=strategy,
                    ),
                })

                # Separate boost query for this discovery source.
                if boost_keyword_ids:

                    discovery_tasks.append({
                        "source": source_name,
                        "media_type": media_type,
                        "priority": source_priority,
                        "is_boost": True,
                        "task": self._run_discovery_query(
                            row=row,
                            media_type=media_type,
                            source_name=source_name,
                            source_ids=source_ids,
                            region=region,
                            language=language,
                            page=page,
                            keyword_ids=boost_keyword_ids,
                            strategy=strategy,
                        ),
                    })

        # Execute all provider, network and company requests
        # concurrently, including the optional boost queries.
        discovery_responses = await asyncio.gather(
            *[
                task_info["task"]
                for task_info in discovery_tasks
            ],
            return_exceptions=True,
        )

        # --------------------------------------------------
        # 5. MERGE DISCOVERY RESULTS IN PRIORITY ORDER
        # --------------------------------------------------

        for task_info, payload in zip(
            discovery_tasks,
            discovery_responses,
        ):

            if isinstance(payload, Exception):

                logger.warning(
                    "Discovery task failed: slider=%s source=%s "
                    "media_type=%s error=%s",
                    row.key,
                    task_info["source"],
                    task_info["media_type"],
                    str(payload),
                )

                continue

            if not payload:
                continue

            if int(payload.get("total_pages") or 0) > page:
                has_more = True

            source_priority = task_info["priority"]
            media_type = task_info["media_type"]
            is_boost = task_info["is_boost"]

            for item in payload.get("results", []):

                tmdb_id = item.get("id")

                if not tmdb_id:
                    continue

                key = (tmdb_id, media_type)

                if key in excluded:
                    continue

                if is_boost:
                    boosted_keys.add(key)

                # Because tasks are processed in source-priority
                # order, a provider result wins over a network
                # result, and a network result wins over a company
                # result when the same title appears more than once.
                candidates.setdefault(
                    key,
                    (
                        item,
                        media_type,
                        False,
                        source_priority,
                    ),
                )

        # --------------------------------------------------
        # 6. FILTER AND NORMALIZE
        # --------------------------------------------------

        normalized_entries = []
        curated_results = []

        for key, (
            item,
            item_media_type,
            is_curated,
            source_priority,
        ) in candidates.items():

            if not self._allowed_for_profile(
                item,
                viewer_profile,
            ):
                continue

            normalized_item = self._normalize_title(
                item,
                item_media_type,
            )

            if is_curated:
                curated_results.append(normalized_item)
            else:
                normalized_entries.append(
                    (
                        normalized_item,
                        source_priority,
                    )
                )

        # --------------------------------------------------
        # 7. RANK RESULTS
        # --------------------------------------------------

        preferences = viewer_profile.preferences or {}

        if not isinstance(preferences, dict):
            preferences = {}

        preferred_genres = self._clean_ids(
            preferences.get("preferred_genres", [])
        )

        def score(item):

            genre_overlap = len(
                set(item["genre_ids"]) & set(preferred_genres)
            )

            return (
                genre_overlap * 10
                + item["popularity"]
                + item["vote_average"] * 2
            )

        def is_boosted(item):
            return (
                item["tmdb_id"],
                item["media_type"],
            ) in boosted_keys

        if strategy == "top_picks":

            normalized_entries.sort(
                key=lambda entry: (
                    is_boosted(entry[0]),
                    -entry[1],
                    score(entry[0]),
                ),
                reverse=True,
            )

        elif strategy in {
            "provider_recent",
            "company_recent",
            "network_recent",
            "recent",
            "latest",
            "newest",
            "new_releases",
        }:

            normalized_entries.sort(
                key=lambda entry: (
                    is_boosted(entry[0]),
                    -entry[1],
                    entry[0].get("release_date") or "",
                ),
                reverse=True,
            )

        elif strategy in {
            "top_rated",
            "highest_rated",
        }:

            normalized_entries.sort(
                key=lambda entry: (
                    is_boosted(entry[0]),
                    -entry[1],
                    entry[0]["vote_average"],
                    entry[0]["vote_count"],
                ),
                reverse=True,
            )

        else:

            normalized_entries.sort(
                key=lambda entry: (
                    is_boosted(entry[0]),
                    -entry[1],
                    entry[0]["popularity"],
                ),
                reverse=True,
            )

        normalized = [
            entry[0]
            for entry in normalized_entries
        ]

        # Curated titles are deliberately placed first.
        results = curated_results + normalized

        # --------------------------------------------------
        # 8. FINAL DEDUPLICATION
        # --------------------------------------------------

        unique = []
        seen = set()

        for item in results:

            key = (
                item["tmdb_id"],
                item["media_type"],
            )

            if key not in seen:
                unique.append(item)
                seen.add(key)

        # Respect configured row size.
        configured_page_size = (
            row.page_size
            or platform_profile.default_row_count
            or 20
        )

        page_size = max(
            int(configured_page_size),
            1,
        )

        return unique[:page_size], has_more

    # ==================================================
    # BUILD PLATFORM HOMEPAGE
    # ==================================================

    async def home(
        self,
        db: Session,
        platform_id: UUID,
        viewer_profile: Profile,
    ):

        (
            platform,
            platform_profile,
            rows,
            providers,
            platform_networks,
            platform_companies,
            slider_config,
        ) = self._load_config(
            db,
            platform_id,
        )

        sliders = []

        # --------------------------------------------------
        # SUPPORTED PLATFORM MEDIA TYPES
        # --------------------------------------------------

        supported_media_types = []

        if getattr(platform, "supports_movies", True):
            supported_media_types.append("movie")

        if getattr(platform, "supports_tv_shows", True):
            supported_media_types.append("tv")

        # Reuse availability checks across sliders in this request.
        availability_cache = {}

        # --------------------------------------------------
        # CONTINUE WATCHING
        # --------------------------------------------------

        from app.services.content import (
            _get_continue_watching_results,
        )

        try:
            with SyncTMDBClient() as sync_tmdb:

                continue_results = _get_continue_watching_results(
                    db=db,
                    tmdb=sync_tmdb,
                    platform=platform,
                    profile=viewer_profile,
                )

            if continue_results:

                sliders.append({
                    "key": "continue_watching",
                    "title": f"Continue Watching on {platform.name}",
                    "strategy": "continue_watching",
                    "media_scope": "mixed",
                    "results": continue_results,
                })

        except Exception as exc:

            logger.warning(
                "Continue Watching failed: %s",
                str(exc),
            )

        # --------------------------------------------------
        # DISCOVERY SLIDERS
        # --------------------------------------------------

        for row in rows:

            row_config = slider_config.get(
                row.id,
                {},
            )

            results, has_more = await self._query_row(
                row=row,
                viewer_profile=viewer_profile,
                platform_profile=platform_profile,
                providers=providers,
                platform_networks=platform_networks,
                platform_companies=platform_companies,
                slider_config=row_config,
                supported_media_types=supported_media_types,
                availability_cache=availability_cache,
                page=1,
            )

            sliders.append({
                "key": row.key,
                "title": row.title,
                "strategy": row.strategy,
                "media_scope": row.media_scope,
                "results": results,
            })

            logger.info(
                "Platform slider assembled: platform=%s slider=%s "
                "results=%s has_more=%s",
                platform.slug,
                row.key,
                len(results),
                has_more,
            )

        # --------------------------------------------------
        # FRONTEND RESPONSE
        # --------------------------------------------------

        return {
            "platform": {
                "id": str(platform.id),
                "name": platform.name,
                "slug": platform.slug,
                "icon": (
                    platform.icon
                    if platform.icon
                    else None
                ),
            },
            "user": {
                "profile_id": str(viewer_profile.id),
                "name": viewer_profile.name,
                "avatar_url": viewer_profile.avatar_key,
                "account_type": (
                    "Kids"
                    if viewer_profile.is_kids_profile
                    else "Adult"
                ),
            },
            "region": platform_profile.region_code or "US",
            "language": platform_profile.language or "en-US",
            "sliders": sliders,
        }
