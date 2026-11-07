from typing import Any
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.commercial import StreamingPlatform
from app.models.platform_config import PlatformProfile, PlatformProvider, PlatformCompany, PlatformNetwork, SliderDefinition
from app.services.tmdb import TMDBClient
from app.schemas.platform import ContentCard, SliderSection

class PlatformHomeService:
    def __init__(self, tmdb: TMDBClient | None = None):
        self.tmdb = tmdb or TMDBClient()

    def _load_config(self, db: Session, slug: str):
        platform = db.scalar(select(StreamingPlatform).where(StreamingPlatform.slug == slug, StreamingPlatform.is_active.is_(True)))
        if not platform:
            return None
        profile = db.scalar(select(PlatformProfile).where(PlatformProfile.platform_id == platform.id, PlatformProfile.enabled.is_(True)))
        rows = db.scalars(select(SliderDefinition).where(
            SliderDefinition.platform_id == platform.id, SliderDefinition.enabled.is_(True)
        ).order_by(SliderDefinition.display_order)).all()
        providers = db.scalars(
            select(PlatformProvider).where(
                PlatformProvider.platform_id == platform.id,
                PlatformProvider.is_active.is_(True),
            )
        ).all()

        companies = db.scalars(
            select(PlatformCompany).where(
                PlatformCompany.platform_id == platform.id,
                PlatformCompany.include_in_discovery.is_(True),
                PlatformCompany.verification_status == "verified",
            )
        ).all()

        networks = db.scalars(
            select(PlatformNetwork).where(
                PlatformNetwork.platform_id == platform.id,
                PlatformNetwork.include_in_discovery.is_(True),
                PlatformNetwork.is_active.is_(True),
            )
        ).all()

    def _card(self, item: dict[str, Any], media_type: str) -> ContentCard:
        return ContentCard(
            tmdb_id=item["id"],
            media_type=item.get("media_type", media_type),
            title=item.get("title") or item.get("name") or item.get("original_name") or "Untitled",
            overview=item.get("overview"),
            poster_path=item.get("poster_path"),
            backdrop_path=item.get("backdrop_path"),
            vote_average=item.get("vote_average"),
            release_date=item.get("release_date") or item.get("first_air_date"),
            genre_ids=item.get("genre_ids") or [],
        )
##ZA
    def _normalize_media_scope(self, media_scope: str) -> list[str]:
        """
        Convert our database media-scope names into TMDB media types.
        """

        scope = (media_scope or "").strip().lower()

        media_scope_map = {
            "mixed": ["movie", "tv"],
            "movies": ["movie"],
            "movie": ["movie"],
            "tv_shows": ["tv"],
            "tv": ["tv"],
            "series": ["tv"],
            "shows": ["tv"],
        }

        return media_scope_map.get(scope, [])

    def _clean_ids(self, values) -> list[int]:
        """
        Convert database TMDB IDs into unique integers.
        Invalid or empty IDs are ignored.
        """

        cleaned = []

        for value in values:
            try:
                value = int(value)

                if value > 0 and value not in cleaned:
                    cleaned.append(value)

            except (TypeError, ValueError):
                continue

        return cleaned

    def _get_sort_order(self, strategy: str, media_type: str) -> str:
        """
        TMDB uses different date fields for movies and TV shows.
        """

        if strategy in {"provider_recent", "company_recent", "network_recent"}:
            if media_type == "movie":
                return "primary_release_date.desc"

            return "first_air_date.desc"

        if strategy in {
            "popular",
            "provider_popular",
            "company_popular",
            "network_popular",
            "provider_genre",
            "company_genre",
            "network_genre",
        }:
            return "popularity.desc"

        if strategy == "top_rated":
            return "vote_average.desc"

        return "popularity.desc"


    async def _query_row(
        self,
        row,
        profile,
        providers,
        companies,
        networks,
        page: int,
    ):
        region = (
            profile.region_code.strip().upper()
            if profile and profile.region_code
            else "US"
        )

        language = (
            profile.language
            if profile and profile.language
            else "en-US"
        )

        strategy = (row.strategy or "").strip().lower()

        media_types = self._normalize_media_scope(row.media_scope)

        if not media_types:
            return [], False

        # Provider IDs: only active watch-provider mappings
        provider_ids = self._clean_ids([
            p.external_id
            for p in providers
            if p.provider_kind == "watch_provider"
            and (
                not p.region_code
                or p.region_code.strip().upper() == region
            )
        ])

        # Company IDs: only verified companies included in discovery
        company_ids = self._clean_ids([
            c.tmdb_company_id
            for c in companies
            if c.include_in_discovery
        ])

        # Network IDs: only active networks included in discovery
        network_ids = self._clean_ids([
            n.tmdb_network_id
            for n in networks
            if n.include_in_discovery
        ])

        # Validate required mappings
        if strategy.startswith("provider_") and not provider_ids:
            return [], False

        if strategy.startswith("company_") and not company_ids:
            return [], False

        if strategy.startswith("network_") and not network_ids:
            return [], False

        # Network strategies must only return TV shows
        if strategy.startswith("network_"):
            media_types = ["tv"]

        items = []
        total_pages = 1

        for media_type in media_types:

            params: dict[str, Any] = {
                "page": page,
                "include_adult": "false",
                "language": language,
                "sort_by": self._get_sort_order(
                    strategy,
                    media_type,
                ),
            }

            if media_type == "movie":
                params["region"] = region

            # Provider strategy
            if strategy.startswith("provider_"):
                params["with_watch_providers"] = "|".join(
                    str(value) for value in provider_ids
                )
                params["watch_region"] = region
                params["with_watch_monetization_types"] = "flatrate"

            # Company strategy
            elif strategy.startswith("company_"):
                params["with_companies"] = "|".join(
                    str(value) for value in company_ids
                )

            # Network strategy
            elif strategy.startswith("network_"):
                params["with_networks"] = "|".join(
                    str(value) for value in network_ids
                )

            # Genre filtering
            if row.genre_ids:
                genre_ids = self._clean_ids(row.genre_ids)

                if genre_ids:
                    params["with_genres"] = "|".join(
                        str(value) for value in genre_ids
                    )

            # Top-rated filtering
            if strategy == "top_rated":
                params["vote_count.gte"] = 100

            # Exclude future releases
            if strategy.endswith("_recent"):
                if media_type == "movie":
                    params["primary_release_date.lte"] = (
                        date.today().isoformat()
                    )
                else:
                    params["first_air_date.lte"] = (
                        date.today().isoformat()
                    )

            # Debug: inspect the exact query
            print(
                f"\n========== PLATFORM SLIDER: {row.key} =========="
            )
            print("STRATEGY:", strategy)
            print("MEDIA TYPE:", media_type)
            print("REGION:", region)
            print("TMDB PARAMETERS:", params)

            if strategy == "trending":
                payload = await self.tmdb.trending(
                    media_type,
                    "week",
                    page,
                )
            else:
                payload = await self.tmdb.discover(
                    media_type,
                    params,
                )

            total_pages = max(
                total_pages,
                int(payload.get("total_pages") or 1),
            )

            for item in payload.get("results", []):

                if not item.get("id"):
                    continue

                items.append(
                    self._card(item, media_type)
                )

        # Remove duplicates
        unique = []
        seen = set()

        for item in items:
            key = (item.tmdb_id, item.media_type)

            if key not in seen:
                unique.append(item)
                seen.add(key)

        page_size = max(int(row.page_size or 20), 1)

        return (
            unique[:page_size],
            page < total_pages,
        )

    async def home(self, db: Session, slug: str, profile_id):
        config = self._load_config(db, slug)
        if not config:
            return None
        platform, profile, rows, providers, companies, networks = config
        sections = []
        for row in rows:
            items, has_more = await self._query_row(row, profile, providers, companies, networks, page=1)
            sections.append(SliderSection(key=row.key, title=row.title, items=items, page=1, has_more=has_more))
        return {"platform": {"slug": platform.slug, "name": platform.name}, "profile_id": str(profile_id), "sections": sections}
