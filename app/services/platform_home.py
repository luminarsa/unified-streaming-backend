
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
    # Internal franchise-expansion settings; not TMDB discover parameters.
    "expand_curated_titles",
    "related_content_sources",
    "related_titles_per_seed",
    "related_min_genre_match",
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

        platform_companies = db.scalars(
            select(PlatformCompany).where(
                PlatformCompany.platform_id == platform.id,
                PlatformCompany.include_in_discovery.is_(True),
            )
        ).all()

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
            "Loaded platform configuration: platform=%s sliders=%s",
            platform.name,
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
    # CLEAN IDS
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
    # SLIDER GOAL CLASSIFICATION
    # ==================================================

    def _get_slider_goal(self, strategy: str) -> str:

        strategy = (strategy or "").strip().lower()

        if strategy in {
            "trending",
            "provider_trending",
            "company_trending",
            "network_trending",
        }:
            return "trending"

        if strategy in {
            "top_rated",
            "highest_rated",
        }:
            return "top_rated"

        if strategy in {
            "provider_recent",
            "company_recent",
            "network_recent",
            "recent",
            "latest",
            "newest",
            "new_releases",
        }:
            return "recent"

        if strategy in {
            "top_picks",
            "personalized",
            "personalised",
        }:
            return "personalized"

        if strategy in {
            "provider_genre",
            "company_genre",
            "network_genre",
            "genre",
        }:
            return "genre"

        return "popular"

    # ==================================================
    # GET TMDB DISCOVERY SORT ORDER
    # ==================================================

    def _get_sort_order(
        self,
        strategy: str,
        media_type: str,
    ) -> str:

        goal = self._get_slider_goal(strategy)

        if goal == "recent":

            return (
                "primary_release_date.desc"
                if media_type == "movie"
                else "first_air_date.desc"
            )

        if goal == "top_rated":
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
    # CHECK ACTUAL SUBSCRIPTION AVAILABILITY
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
                "Availability check failed: title=%s error=%s",
                tmdb_id,
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
    # FETCH RELATED TITLES FOR A FRANCHISE SEED
    # ==================================================

    async def _get_related_titles(
        self,
        tmdb_id: int,
        media_type: str,
        source: str,
        language: str,
    ) -> list[dict]:
        """
        Fetch TMDB recommendations or similar titles for a seed title.

        Supported sources:
        - recommendations
        - similar
        """

        if source not in {"recommendations", "similar"}:
            return []

        try:
            payload = await self.tmdb.get(
                f"/{media_type}/{tmdb_id}/{source}",
                params={
                    "language": language,
                    "page": 1,
                },
            )

            return payload.get("results", [])

        except Exception as exc:

            logger.warning(
                "Franchise expansion failed: seed=%s "
                "media_type=%s source=%s error=%s",
                tmdb_id,
                media_type,
                source,
                str(exc),
            )

            return []


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

        goal = self._get_slider_goal(strategy)

        if goal == "top_rated":
            params["vote_count.gte"] = 100

        if goal == "recent":

            date_field = (
                "primary_release_date.lte"
                if media_type == "movie"
                else "first_air_date.lte"
            )

            params[date_field] = date.today().isoformat()

        self._apply_overrides(
            params,
            row.query_overrides or {},
        )

        # Keep source filters protected from overrides.

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
                "Discovery failed: slider=%s source=%s "
                "media_type=%s error=%s",
                row.key,
                source_name,
                media_type,
                str(exc),
            )

            return None

    # ==================================================
    # FETCH ACTUAL TMDB TRENDING ORDER
    # ==================================================

    async def _get_trending_order(
        self,
        media_type: str,
        page: int,
    ) -> dict:

        try:
            payload = await self.tmdb.trending(
                media_type,
                window="week",
                page=page,
            )

            results = payload.get("results", [])

            return {
                item["id"]: position
                for position, item in enumerate(results)
                if item.get("id")
            }

        except Exception as exc:

            logger.warning(
                "Trending lookup failed: media_type=%s error=%s",
                media_type,
                str(exc),
            )

            return {}

    # ==================================================
    # SOURCE RELEVANCE FOR EACH SLIDER GOAL
    # ==================================================

    def _get_source_score(
        self,
        sources: set[str],
        strategy: str,
    ) -> int:

        strategy = (strategy or "").lower()

        # Franchise-related titles receive priority over ordinary
        # provider, network and company discovery candidates.
        if "franchise" in sources:
            return 40

        # A slider focused on providers prioritises provider results.
        if strategy.startswith("provider_"):
            return 30 if "provider" in sources else 0

        # A network slider prioritises network results.
        if strategy.startswith("network_"):
            return 30 if "network" in sources else 0

        # A company slider prioritises production company results.
        if strategy.startswith("company_"):
            return 30 if "company" in sources else 0

        # Generic sliders treat all discovery sources equally.
        return 0

    # ==================================================
    # RANK ONE SLIDER'S CONTENT
    # ==================================================

    def _rank_slider_results(
        self,
        entries: list[dict],
        strategy: str,
        viewer_profile: Profile,
        trending_order: dict,
    ) -> list[dict]:

        goal = self._get_slider_goal(strategy)

        preferences = viewer_profile.preferences or {}

        if not isinstance(preferences, dict):
            preferences = {}

        preferred_genres = set(
            self._clean_ids(
                preferences.get("preferred_genres", [])
            )
        )

        def genre_overlap(item):

            return len(
                set(item["genre_ids"]) & preferred_genres
            )

        def sort_key(entry):

            item = entry["item"]

            source_score = self._get_source_score(
                entry["sources"],
                strategy,
            )

            boosted = entry["boosted"]

            popularity = item["popularity"]
            vote_average = item["vote_average"]
            vote_count = item["vote_count"]

            if goal == "trending":

                trend_position = trending_order.get(
                    item["tmdb_id"],
                    9999,
                )

                return (
                    boosted,
                    trend_position,
                    source_score,
                    popularity,
                )

            if goal == "top_rated":

                return (
                    boosted,
                    source_score,
                    vote_average,
                    vote_count,
                    popularity,
                )

            if goal == "recent":

                return (
                    boosted,
                    source_score,
                    item.get("release_date") or "",
                    popularity,
                )

            if goal == "personalized":

                return (
                    boosted,
                    genre_overlap(item),
                    source_score,
                    popularity,
                    vote_average,
                )

            if goal == "genre":

                return (
                    boosted,
                    genre_overlap(item),
                    source_score,
                    popularity,
                )

            # Default goal: popular content.
            return (
                boosted,
                source_score,
                popularity,
                vote_average,
            )

        entries.sort(
            key=sort_key,
            reverse=True,
        )

        return entries

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

        goal = self._get_slider_goal(strategy)

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
        # PROVIDERS
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
        # NETWORKS
        # --------------------------------------------------

        network_values = [
            item.tmdb_network_id
            for item in platform_networks
        ]

        network_values.extend([
            item.tmdb_network_id
            for item in slider_config["networks"]
        ])

        network_values.extend(
            (row.query_overrides or {}).get(
                "with_networks",
                [],
            )
            if isinstance(
                (row.query_overrides or {}).get("with_networks", []),
                list,
            )
            else str(
                (row.query_overrides or {}).get("with_networks", "")
            ).replace(",", "|").split("|")
        )

        network_ids = self._clean_ids(network_values)

        # --------------------------------------------------
        # COMPANIES
        # --------------------------------------------------

        company_values = [
            item.tmdb_company_id
            for item in platform_companies
        ]

        company_values.extend([
            item.tmdb_company_id
            for item in slider_config["companies"]
        ])

        override_companies = (
            row.query_overrides or {}
        ).get("with_companies", [])

        if not isinstance(override_companies, list):
            override_companies = str(
                override_companies
            ).replace(",", "|").split("|")

        company_values.extend(override_companies)

        company_ids = self._clean_ids(company_values)

        # Network discovery applies to television.
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

        # Candidate records retain source information.
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

            candidates[key] = {
                "item": item,
                "media_type": curated_item.media_type,
                "curated": True,
                "curated_priority": curated_item.priority,
                "sources": set(),
                "boosted": False,
            }


        # --------------------------------------------------
        # 1B. FRANCHISE / CURATED TITLE EXPANSION
        # --------------------------------------------------

        overrides = row.query_overrides or {}

        expand_curated_titles = bool(
            overrides.get("expand_curated_titles", False)
        )

        if expand_curated_titles and curated:

            # Only allow the two supported TMDB related-content sources.
            related_sources = overrides.get(
                "related_content_sources",
                ["recommendations", "similar"],
            )

            if isinstance(related_sources, str):
                related_sources = [
                    value.strip().lower()
                    for value in related_sources.replace(",", "|").split("|")
                    if value.strip()
                ]

            if not isinstance(related_sources, list):
                related_sources = [
                    "recommendations",
                    "similar",
                ]

            related_sources = [
                source.strip().lower()
                for source in related_sources
                if isinstance(source, str)
                and source.strip().lower() in {
                    "recommendations",
                    "similar",
                }
            ]

            # Remove duplicate source names.
            related_sources = list(dict.fromkeys(related_sources))

            # Maximum related titles requested per seed.
            try:
                related_limit = int(
                    overrides.get("related_titles_per_seed", 15)
                )
            except (TypeError, ValueError):
                related_limit = 15

            related_limit = max(
                1,
                min(related_limit, 30),
            )

            # If the slider has configured genres, related titles
            # should match at least one of those genres by default.
            try:
                minimum_genre_match = int(
                    overrides.get("related_min_genre_match", 1)
                )
            except (TypeError, ValueError):
                minimum_genre_match = 1

            minimum_genre_match = max(
                0,
                min(minimum_genre_match, 5),
            )

            slider_genres = set(
                self._clean_ids(row.genre_ids or [])
            )

            related_tasks = []

            for curated_item in curated:

                if curated_item.media_type not in media_types:
                    continue

                for source in related_sources:

                    related_tasks.append({
                        "seed_id": curated_item.tmdb_id,
                        "media_type": curated_item.media_type,
                        "source": source,
                        "task": self._get_related_titles(
                            tmdb_id=curated_item.tmdb_id,
                            media_type=curated_item.media_type,
                            source=source,
                            language=language,
                        ),
                    })

            related_responses = await asyncio.gather(
                *[
                    task_info["task"]
                    for task_info in related_tasks
                ],
                return_exceptions=True,
            )

            related_candidates = {}

            for task_info, related_items in zip(
                related_tasks,
                related_responses,
            ):

                if isinstance(related_items, Exception):
                    continue

                for item in (related_items or [])[:related_limit]:

                    tmdb_id = item.get("id")

                    if not tmdb_id:
                        continue

                    related_media_type = task_info["media_type"]

                    key = (
                        tmdb_id,
                        related_media_type,
                    )

                    if key in excluded:
                        continue

                    # Never replace a curated title with a recommendation.
                    if key in candidates and candidates[key]["curated"]:
                        continue

                    # Apply the selected profile's restrictions early.
                    if not self._allowed_for_profile(
                        item,
                        viewer_profile,
                    ):
                        continue

                    # Respect the slider's configured genre focus.
                    if slider_genres and minimum_genre_match > 0:

                        item_genres = self._get_genre_ids(item)

                        if len(item_genres & slider_genres) < minimum_genre_match:
                            continue

                    if key not in related_candidates:

                        related_candidates[key] = {
                            "item": item,
                            "media_type": related_media_type,
                            "sources": {"franchise"},
                        }

            # Validate actual subscription availability before adding
            # related titles to the slider.
            availability_tasks = []

            related_keys = list(related_candidates.keys())

            for key in related_keys:

                tmdb_id, related_media_type = key

                availability_tasks.append(
                    self._has_subscription_availability(
                        tmdb_id=tmdb_id,
                        media_type=related_media_type,
                        region=region,
                        provider_ids=provider_ids,
                        availability_cache=availability_cache,
                    )
                )

            availability_results = await asyncio.gather(
                *availability_tasks,
                return_exceptions=True,
            )

            for key, available in zip(
                related_keys,
                availability_results,
            ):

                if isinstance(available, Exception) or not available:
                    continue

                related_candidate = related_candidates[key]

                if key in candidates:

                    # A title may already have come from provider,
                    # network, company or collection discovery.
                    candidates[key]["sources"].add("franchise")

                else:

                    candidates[key] = {
                        "item": related_candidate["item"],
                        "media_type": related_candidate["media_type"],
                        "curated": False,
                        "curated_priority": None,
                        "sources": {"franchise"},
                        "boosted": False,
                    }

            logger.info(
                "Franchise expansion completed: slider=%s "
                "seeds=%s related_candidates=%s",
                row.key,
                len(curated),
                len(related_candidates),
            )

        # --------------------------------------------------
        # 2. COLLECTION CONTENT
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

                candidates[key] = {
                    "item": item,
                    "media_type": media_type,
                    "curated": False,
                    "curated_priority": None,
                    "sources": {"collection"},
                    "boosted": False,
                }

        # --------------------------------------------------
        # 3. KEYWORDS
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
        # 4. DISCOVERY FROM ALL THREE SOURCES
        # --------------------------------------------------

        discovery_sources = [
            ("provider", provider_ids),
            ("network", network_ids),
            ("company", company_ids),
        ]

        discovery_tasks = []

        for media_type in media_types:

            for source_name, source_ids in discovery_sources:

                if not source_ids:
                    continue

                discovery_tasks.append({
                    "source": source_name,
                    "media_type": media_type,
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

                if boost_keyword_ids:

                    discovery_tasks.append({
                        "source": source_name,
                        "media_type": media_type,
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

        # Actual trending data is used as a ranking signal.
        # It does not replace the three discovery sources.
        trending_tasks = {}

        if goal == "trending":

            for media_type in media_types:

                trending_tasks[media_type] = (
                    self._get_trending_order(
                        media_type,
                        page,
                    )
                )

        all_tasks = [
            task_info["task"]
            for task_info in discovery_tasks
        ]

        trending_media_types = list(
            trending_tasks.keys()
        )

        all_tasks.extend([
            trending_tasks[media_type]
            for media_type in trending_media_types
        ])

        responses = await asyncio.gather(
            *all_tasks,
            return_exceptions=True,
        )

        discovery_responses = responses[
            :len(discovery_tasks)
        ]

        trending_responses = responses[
            len(discovery_tasks):
        ]

        trending_order = {}

        for media_type, payload in zip(
            trending_media_types,
            trending_responses,
        ):

            if isinstance(payload, Exception):
                continue

            trending_order[media_type] = payload or {}

        # --------------------------------------------------
        # 5. MERGE DISCOVERY RESULTS
        # --------------------------------------------------

        for task_info, payload in zip(
            discovery_tasks,
            discovery_responses,
        ):

            if isinstance(payload, Exception):

                logger.warning(
                    "Discovery task failed: slider=%s source=%s error=%s",
                    row.key,
                    task_info["source"],
                    str(payload),
                )

                continue

            if not payload:
                continue

            if int(payload.get("total_pages") or 0) > page:
                has_more = True

            source_name = task_info["source"]
            media_type = task_info["media_type"]
            is_boost = task_info["is_boost"]

            for item in payload.get("results", []):

                tmdb_id = item.get("id")

                if not tmdb_id:
                    continue

                key = (tmdb_id, media_type)

                if key in excluded:
                    continue

                if key not in candidates:

                    candidates[key] = {
                        "item": item,
                        "media_type": media_type,
                        "curated": False,
                        "curated_priority": None,
                        "sources": set(),
                        "boosted": False,
                    }

                candidate = candidates[key]

                candidate["sources"].add(source_name)

                if is_boost:
                    candidate["boosted"] = True

        # --------------------------------------------------
        # 6. PROFILE FILTERING AND NORMALIZATION
        # --------------------------------------------------

        curated_entries = []
        normal_entries = []

        for key, candidate in candidates.items():

            item = candidate["item"]

            if not self._allowed_for_profile(
                item,
                viewer_profile,
            ):
                continue

            normalized_item = self._normalize_title(
                item,
                candidate["media_type"],
            )

            entry = {
                "item": normalized_item,
                "sources": candidate["sources"],
                "boosted": candidate["boosted"],
                "curated": candidate["curated"],
                "curated_priority": candidate["curated_priority"],
            }

            if candidate["curated"]:
                curated_entries.append(entry)
            else:
                normal_entries.append(entry)

        # --------------------------------------------------
        # 7. RANK ACCORDING TO THE SLIDER GOAL
        # --------------------------------------------------

        for media_type, order in trending_order.items():

            # Trending positions are stored per media type.
            for entry in normal_entries:

                item = entry["item"]

                if item["media_type"] == media_type:
                    item["_trending_position"] = order.get(
                        item["tmdb_id"],
                        9999,
                    )

        # Ranking function uses the temporary trending position.
        if goal == "trending":

            for entry in normal_entries:

                item = entry["item"]

                item["_trending_position"] = (
                    item.get("_trending_position", 9999)
                )

            normal_entries.sort(
                key=lambda entry: (
                    entry["boosted"],
                    -entry["item"].get("_trending_position", 9999),
                    self._get_source_score(
                        entry["sources"],
                        strategy,
                    ),
                    entry["item"]["popularity"],
                ),
                reverse=True,
            )

        else:

            normal_entries = self._rank_slider_results(
                entries=normal_entries,
                strategy=strategy,
                viewer_profile=viewer_profile,
                trending_order={},
            )

        # Preserve configured curated priority.
        curated_entries.sort(
            key=lambda entry: (
                entry["curated_priority"]
                if entry["curated_priority"] is not None
                else 999999
            )
        )

        # --------------------------------------------------
        # 8. ASSEMBLE RESULTS
        # --------------------------------------------------

        results = [
            entry["item"]
            for entry in curated_entries
        ]

        results.extend([
            entry["item"]
            for entry in normal_entries
        ])

        # --------------------------------------------------
        # 9. REMOVE DUPLICATES
        # --------------------------------------------------

        unique = []
        seen = set()

        for item in results:

            key = (
                item["tmdb_id"],
                item["media_type"],
            )

            if key in seen:
                continue

            seen.add(key)

            # Internal ranking fields must not reach the frontend.
            item.pop("_trending_position", None)

            unique.append(item)


        configured_page_size = (
            row.page_size
            or platform_profile.default_row_count
            or 20
        )

        page_size = max(
            int(configured_page_size),
            1,
        )

        # Keep a larger reserve pool so the diversity engine
        # can replace titles already displayed in other sliders.
        candidate_limit = min(
            max(
                page_size * 3,
                page_size + 20,
            ),
            100,
        )

        # Preserve curated metadata internally until the diversity
        # engine has selected the final titles for this slider.
        for item in unique:

            item["_is_curated"] = False
            item["_curated_priority"] = None

        # Reapply curated metadata using the original curated entries.
        curated_metadata = {}

        for entry in curated_entries:

            item = entry["item"]

            key = (
                item["tmdb_id"],
                item["media_type"],
            )

            curated_metadata[key] = {
                "priority": entry["curated_priority"],
            }

        for item in unique:

            key = (
                item["tmdb_id"],
                item["media_type"],
            )

            metadata = curated_metadata.get(key)

            if metadata is not None:

                item["_is_curated"] = True
                item["_curated_priority"] = metadata["priority"]

        return unique[:candidate_limit], has_more

    # ==================================================
    # CROSS-SLIDER DIVERSITY ENGINE
    # ==================================================

    def _apply_slider_diversity(
        self,
        sliders: list[dict],
    ) -> list[dict]:
        """
        Reduces unnecessary title repetition across homepage sliders.

        Rules:
        - A title should normally appear in no more than 2 sliders.
        - Curated titles are protected in their configured slider.
        - Alternative candidates replace repeated titles where possible.
        - Repeated titles are allowed when there are not enough alternatives.
        - Internal ranking fields are removed before returning the response.
        """

        appearance_counts = {}

        for slider in sliders:

            # Continue Watching has no discovery candidate pool.
            # Count its titles so discovery sliders can prefer alternatives.
            if "_candidate_pool" not in slider:

                for item in slider.get("results", []):

                    key = (
                        item.get("tmdb_id"),
                        item.get("media_type"),
                    )

                    if key[0] is None or key[1] is None:
                        continue

                    appearance_counts[key] = (
                        appearance_counts.get(key, 0) + 1
                    )

                continue

            candidate_pool = slider.pop(
                "_candidate_pool",
                [],
            )

            page_size = slider.pop(
                "_page_size",
                20,
            )

            page_size = max(int(page_size or 20), 1)

            curated_candidates = [
                item
                for item in candidate_pool
                if item.get("_is_curated", False)
            ]

            normal_candidates = [
                item
                for item in candidate_pool
                if not item.get("_is_curated", False)
            ]

            # Curated titles are already sorted by configured priority.
            selected = curated_candidates[:page_size]

            selected_keys = {
                (
                    item.get("tmdb_id"),
                    item.get("media_type"),
                )
                for item in selected
            }

            # First pass: prefer titles that have appeared fewer than
            # two times across the homepage.
            for item in normal_candidates:

                if len(selected) >= page_size:
                    break

                key = (
                    item.get("tmdb_id"),
                    item.get("media_type"),
                )

                if key in selected_keys:
                    continue

                if appearance_counts.get(key, 0) >= 2:
                    continue

                selected.append(item)
                selected_keys.add(key)

            # Second pass: if the row is still not full, allow repeats.
            # This prevents the diversity engine from creating short rows.
            if len(selected) < page_size:

                for item in normal_candidates:

                    if len(selected) >= page_size:
                        break

                    key = (
                        item.get("tmdb_id"),
                        item.get("media_type"),
                    )

                    if key in selected_keys:
                        continue

                    selected.append(item)
                    selected_keys.add(key)

            # Update the homepage-wide appearance counts.
            for item in selected:

                key = (
                    item.get("tmdb_id"),
                    item.get("media_type"),
                )

                appearance_counts[key] = (
                    appearance_counts.get(key, 0) + 1
                )

                # Remove internal fields before the frontend response.
                item.pop("_is_curated", None)
                item.pop("_curated_priority", None)
                item.pop("_trending_position", None)

            slider["results"] = selected

        return sliders

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

        supported_media_types = []

        if getattr(platform, "supports_movies", True):
            supported_media_types.append("movie")

        if getattr(platform, "supports_tv_shows", True):
            supported_media_types.append("tv")

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


            configured_page_size = (
                row.page_size
                or platform_profile.default_row_count
                or 20
            )

            page_size = max(
                int(configured_page_size),
                1,
            )

            sliders.append({
                "key": row.key,
                "title": row.title,
                "strategy": row.strategy,
                "media_scope": row.media_scope,

                # The diversity engine will select the final row.
                "results": [],

                # Temporary internal data, removed before the response.
                "_candidate_pool": results,
                "_page_size": page_size,
            })

            logger.info(
                "Platform slider assembled: platform=%s slider=%s "
                "goal=%s results=%s has_more=%s",
                platform.slug,
                row.key,
                self._get_slider_goal(row.strategy),
                len(results),
                has_more,
            )


        # --------------------------------------------------
        # APPLY CROSS-SLIDER DIVERSITY
        # --------------------------------------------------

        sliders = self._apply_slider_diversity(sliders)

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
