
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
    # CLEAN IDS
    # ==================================================

    def _clean_ids(self, values) -> list[int]:

        result = []

        for value in values or []:

            try:
                value = int(value)

                if value > 0 and value not in result:
                    result.append(value)

            except (TypeError, ValueError):
                continue

        return result

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
    # SLIDER GOAL
    # ==================================================

    def _get_slider_goal(self, strategy: str) -> str:

        strategy = (strategy or "").strip().lower()

        if "trending" in strategy:
            return "trending"

        if "top_rated" in strategy or "highest_rated" in strategy:
            return "top_rated"

        if "recent" in strategy or "latest" in strategy:
            return "recent"

        if "genre" in strategy:
            return "genre"

        return "popular"

    # ==================================================
    # DISCOVERY SORT ORDER
    # ==================================================

    def _get_sort_order(
        self,
        strategy: str,
        media_type: str,
    ) -> str:

        goal = self._get_slider_goal(strategy)

        # Popularity is the default for homepage discovery.
        if goal in {"popular", "genre", "recent"}:
            return "popularity.desc"

        if goal == "top_rated":
            return "vote_average.desc"

        if goal == "trending":
            return "popularity.desc"

        return "popularity.desc"

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
    # FETCH CURATED TITLE DETAILS
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
    # FETCH TMDB RECOMMENDATIONS
    # ==================================================

    async def _get_recommendations(
        self,
        tmdb_id: int,
        media_type: str,
        language: str,
    ) -> list[dict]:

        try:
            payload = await self.tmdb.get(
                f"/{media_type}/{tmdb_id}/recommendations",
                params={
                    "language": language,
                    "page": 1,
                },
            )

            return payload.get("results", [])

        except Exception as exc:

            logger.warning(
                "TMDB recommendations failed: title=%s error=%s",
                tmdb_id,
                str(exc),
            )

            return []

    # ==================================================
    # FETCH RELATED CONTENT FROM CURATED SEEDS
    # ==================================================

    async def _get_franchise_candidates(
        self,
        curated_titles: list,
        media_types: list[str],
        language: str,
        profile: Profile,
    ) -> list[dict]:

        tasks = []

        for curated in curated_titles:

            if curated.media_type not in media_types:
                continue

            tasks.append({
                "media_type": curated.media_type,
                "seed_id": curated.tmdb_id,
                "task": self._get_recommendations(
                    tmdb_id=curated.tmdb_id,
                    media_type=curated.media_type,
                    language=language,
                ),
            })

        responses = await asyncio.gather(
            *[item["task"] for item in tasks],
            return_exceptions=True,
        )

        candidates = {}

        for task_info, payload in zip(tasks, responses):

            if isinstance(payload, Exception) or not payload:
                continue

            for item in payload:

                tmdb_id = item.get("id")

                if not tmdb_id:
                    continue

                if not self._allowed_for_profile(item, profile):
                    continue

                key = (
                    int(tmdb_id),
                    task_info["media_type"],
                )

                if key not in candidates:
                    candidates[key] = {
                        "item": item,
                        "media_type": task_info["media_type"],
                        "seed_ids": set(),
                    }

                candidates[key]["seed_ids"].add(
                    task_info["seed_id"]
                )

        results = list(candidates.values())

        # TMDB provides relevance through its recommendation endpoint.
        # We use popularity to order the returned recommendations.
        results.sort(
            key=lambda candidate: (
                float(candidate["item"].get("popularity") or 0),
                len(candidate["seed_ids"]),
            ),
            reverse=True,
        )

        return results

    # ==================================================
    # BUILD DISCOVERY PARAMETERS
    # ==================================================

    def _build_discovery_params(
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
    ) -> dict:

        params = {
            "page": page,
            "include_adult": "false",
            "language": language,
            "sort_by": self._get_sort_order(
                strategy,
                media_type,
            ),
        }

        overrides = row.query_overrides or {}

        # --------------------------------------------------
        # WATCH PROVIDER FILTER
        # --------------------------------------------------

        if source_name == "provider":

            params["with_watch_providers"] = "|".join(
                str(value) for value in source_ids
            )

            params["watch_region"] = region
            params["with_watch_monetization_types"] = "flatrate"

            if media_type == "movie":
                params["region"] = region

        # --------------------------------------------------
        # NETWORK FILTER
        # --------------------------------------------------

        elif source_name == "network":

            params["with_watch_providers"] = "|".join(
                str(value) for value in self._clean_ids(
                    overrides.get("_provider_ids", [])
                )
            )

            params["watch_region"] = region
            params["with_watch_monetization_types"] = "flatrate"

            params["with_networks"] = "|".join(
                str(value) for value in source_ids
            )

        # --------------------------------------------------
        # PRODUCTION COMPANY FILTER
        # --------------------------------------------------

        elif source_name == "company":

            provider_ids = self._clean_ids(
                overrides.get("_provider_ids", [])
            )

            if provider_ids:
                params["with_watch_providers"] = "|".join(
                    str(value) for value in provider_ids
                )

                params["watch_region"] = region
                params["with_watch_monetization_types"] = "flatrate"

                if media_type == "movie":
                    params["region"] = region

            params["with_companies"] = "|".join(
                str(value) for value in source_ids
            )

        # --------------------------------------------------
        # GENRE FILTER
        # --------------------------------------------------

        genre_ids = self._clean_ids(
            row.genre_ids or []
        )

        if genre_ids:
            params["with_genres"] = "|".join(
                str(value) for value in genre_ids
            )

        # --------------------------------------------------
        # KEYWORD FILTER
        # --------------------------------------------------

        if keyword_ids:
            params["with_keywords"] = "|".join(
                str(value) for value in keyword_ids
            )

        # --------------------------------------------------
        # STRATEGY FILTERS
        # --------------------------------------------------

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

        # --------------------------------------------------
        # SAFE TMDB OVERRIDES
        # --------------------------------------------------

        protected = {
            "page",
            "language",
            "include_adult",
            "region",
            "watch_region",
            "with_watch_providers",
            "with_watch_monetization_types",
            "with_networks",
            "with_companies",
            "with_genres",
            "with_keywords",
            "sort_by",
        }

        for key, value in overrides.items():

            if key in protected or key.startswith("_"):
                continue

            if value is None:
                continue

            if isinstance(value, (str, int, float, bool)):
                params[key] = value

            elif isinstance(value, list):
                params[key] = "|".join(
                    str(item) for item in value
                )

        # Always retain provider filtering on network/company queries.
        if source_name in {"network", "company"}:

            provider_ids = self._clean_ids(
                overrides.get("_provider_ids", [])
            )

            if provider_ids:

                params["with_watch_providers"] = "|".join(
                    str(value) for value in provider_ids
                )

                params["watch_region"] = region
                params["with_watch_monetization_types"] = "flatrate"

                if media_type == "movie":
                    params["region"] = region

        return params

    # ==================================================
    # RUN ONE DISCOVERY QUERY
    # ==================================================

    async def _run_discovery_query(
        self,
        row,
        media_type: str,
        source_name: str,
        source_ids: list[int],
        provider_ids: list[int],
        region: str,
        language: str,
        page: int,
        keyword_ids: list[int],
        strategy: str,
    ):

        if not source_ids:
            return None

        overrides = dict(row.query_overrides or {})

        # Internal parameter used only when constructing the query.
        overrides["_provider_ids"] = provider_ids

        # Build parameters using the slider's configured filters.
        params = self._build_discovery_params(
            row=row,
            media_type=media_type,
            source_name=source_name,
            source_ids=source_ids,
            region=region,
            language=language,
            page=page,
            keyword_ids=keyword_ids,
            strategy=strategy,
        )

        # The helper receives the original row overrides. Rebuild the
        # provider filters here so company/network queries also require
        # availability on the platform's provider.
        if source_name in {"network", "company"} and provider_ids:

            params["with_watch_providers"] = "|".join(
                str(value) for value in provider_ids
            )

            params["watch_region"] = region
            params["with_watch_monetization_types"] = "flatrate"

            if media_type == "movie":
                params["region"] = region

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

        overrides = row.query_overrides or {}

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
        # PROVIDER IDS
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

        if not provider_ids:
            logger.warning(
                "Slider has no watch providers configured: %s",
                row.key,
            )
            return [], False

        # --------------------------------------------------
        # NETWORK IDS
        # --------------------------------------------------

        network_values = [
            item.tmdb_network_id
            for item in platform_networks
        ]

        network_values.extend([
            item.tmdb_network_id
            for item in slider_config["networks"]
        ])

        override_networks = overrides.get("with_networks", [])

        if not isinstance(override_networks, list):
            override_networks = str(
                override_networks
            ).replace(",", "|").split("|")

        network_values.extend(override_networks)

        network_ids = self._clean_ids(network_values)

        # --------------------------------------------------
        # COMPANY IDS
        # --------------------------------------------------

        company_values = [
            item.tmdb_company_id
            for item in platform_companies
        ]

        company_values.extend([
            item.tmdb_company_id
            for item in slider_config["companies"]
        ])

        override_companies = overrides.get("with_companies", [])

        if not isinstance(override_companies, list):
            override_companies = str(
                override_companies
            ).replace(",", "|").split("|")

        company_values.extend(override_companies)

        company_ids = self._clean_ids(company_values)

        # --------------------------------------------------
        # MEDIA SCOPE RESTRICTIONS
        # --------------------------------------------------

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

        candidates = {}
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

            if not self._allowed_for_profile(
                item,
                viewer_profile,
            ):
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
            }

        # --------------------------------------------------
        # 2. TMDB FRANCHISE RECOMMENDATIONS
        # --------------------------------------------------

        franchise_mode = bool(
            overrides.get("franchise_mode", False)
        )

        if franchise_mode and curated:

            related_candidates = await self._get_franchise_candidates(
                curated_titles=curated,
                media_types=media_types,
                language=language,
                profile=viewer_profile,
            )

            for related in related_candidates:

                item = related["item"]
                media_type = related["media_type"]

                tmdb_id = item.get("id")

                if not tmdb_id:
                    continue

                key = (int(tmdb_id), media_type)

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
                }

        # --------------------------------------------------
        # 3. TMDB COLLECTIONS
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

                key = (int(tmdb_id), media_type)

                if key in excluded or key in candidates:
                    continue

                if not self._allowed_for_profile(
                    item,
                    viewer_profile,
                ):
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
                }

        # --------------------------------------------------
        # 4. KEYWORD CONFIGURATION
        # --------------------------------------------------

        include_keyword_ids = self._clean_ids([
            item.tmdb_keyword_id
            for item in slider_config["keywords"]
            if item.match_type == "include"
        ])

        # --------------------------------------------------
        # 5. TMDB DISCOVER QUERIES
        # --------------------------------------------------

        discovery_sources = [
            ("provider", provider_ids),
        ]

        # Network/company searches are supplementary filters.
        # They still include the platform's watch provider.
        if network_ids:
            discovery_sources.append(
                ("network", network_ids)
            )

        if company_ids:
            discovery_sources.append(
                ("company", company_ids)
            )

        discovery_tasks = []

        for media_type in media_types:

            for source_name, source_ids in discovery_sources:

                discovery_tasks.append({
                    "source": source_name,
                    "media_type": media_type,
                    "task": self._run_discovery_query(
                        row=row,
                        media_type=media_type,
                        source_name=source_name,
                        source_ids=source_ids,
                        provider_ids=provider_ids,
                        region=region,
                        language=language,
                        page=page,
                        keyword_ids=include_keyword_ids,
                        strategy=strategy,
                    ),
                })

        responses = await asyncio.gather(
            *[
                item["task"]
                for item in discovery_tasks
            ],
            return_exceptions=True,
        )

        # --------------------------------------------------
        # 6. MERGE DISCOVER RESULTS
        # --------------------------------------------------

        for task_info, payload in zip(
            discovery_tasks,
            responses,
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

            media_type = task_info["media_type"]

            for item in payload.get("results", []):

                tmdb_id = item.get("id")

                if not tmdb_id:
                    continue

                key = (
                    int(tmdb_id),
                    media_type,
                )

                if key in excluded:
                    continue

                if key in candidates:
                    continue

                if not self._allowed_for_profile(
                    item,
                    viewer_profile,
                ):
                    continue

                candidates[key] = {
                    "item": item,
                    "media_type": media_type,
                    "curated": False,
                    "curated_priority": None,
                }

        # --------------------------------------------------
        # 7. NORMALIZE AND SORT
        # --------------------------------------------------

        curated_entries = []
        normal_entries = []

        for candidate in candidates.values():

            item = candidate["item"]

            normalized_item = self._normalize_title(
                item,
                candidate["media_type"],
            )

            entry = {
                "item": normalized_item,
                "curated": candidate["curated"],
                "curated_priority": candidate["curated_priority"],
            }

            if candidate["curated"]:
                curated_entries.append(entry)
            else:
                normal_entries.append(entry)

        curated_entries.sort(
            key=lambda entry: (
                entry["curated_priority"]
                if entry["curated_priority"] is not None
                else 999999
            )
        )

        # Popularity descending is the default for all normal
        # homepage slider content, including recommendations and
        # collection titles.
        normal_entries.sort(
            key=lambda entry: (
                entry["item"]["popularity"],
                entry["item"]["vote_count"],
                entry["item"]["vote_average"],
            ),
            reverse=True,
        )

        results = [
            entry["item"]
            for entry in curated_entries
        ]

        results.extend([
            entry["item"]
            for entry in normal_entries
        ])

        # --------------------------------------------------
        # 8. REMOVE DUPLICATES
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
            unique.append(item)

        # --------------------------------------------------
        # 9. RETURN A CANDIDATE POOL
        # --------------------------------------------------

        configured_page_size = (
            row.page_size
            or platform_profile.default_row_count
            or 20
        )

        page_size = max(
            int(configured_page_size),
            1,
        )

        # Fetch a reserve pool so the homepage uniqueness engine
        # can fill rows after removing titles used elsewhere.
        candidate_limit = min(
            max(page_size * 3, page_size + 20),
            100,
        )

        return unique[:candidate_limit], has_more

    # ==================================================
    # CROSS-SLIDER TITLE UNIQUENESS
    # ==================================================

    def _apply_slider_uniqueness(
        self,
        sliders: list[dict],
    ) -> list[dict]:
        """
        Each title may appear only once across the homepage.

        The first slider in display order gets priority.
        Continue Watching titles are also reserved and cannot
        appear again in discovery sliders.
        """

        used_titles = set()

        # --------------------------------------------------
        # RESERVE CONTINUE WATCHING TITLES
        # --------------------------------------------------

        for slider in sliders:

            if "_candidate_pool" in slider:
                continue

            for item in slider.get("results", []):

                key = (
                    item.get("tmdb_id"),
                    item.get("media_type"),
                )

                if key[0] is not None and key[1] is not None:
                    used_titles.add(key)

        # --------------------------------------------------
        # SELECT UNIQUE TITLES FOR EACH DISCOVERY SLIDER
        # --------------------------------------------------

        for slider in sliders:

            if "_candidate_pool" not in slider:
                continue

            candidate_pool = slider.pop(
                "_candidate_pool",
                [],
            )

            page_size = slider.pop(
                "_page_size",
                20,
            )

            page_size = max(
                int(page_size or 20),
                1,
            )

            selected = []

            for item in candidate_pool:

                if len(selected) >= page_size:
                    break

                key = (
                    item.get("tmdb_id"),
                    item.get("media_type"),
                )

                if key[0] is None or key[1] is None:
                    continue

                if key in used_titles:
                    continue

                selected.append(item)
                used_titles.add(key)

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
                "results": [],
                "_candidate_pool": results,
                "_page_size": page_size,
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
        # ENFORCE HOMEPAGE-WIDE UNIQUENESS
        # --------------------------------------------------

        sliders = self._apply_slider_uniqueness(sliders)

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
