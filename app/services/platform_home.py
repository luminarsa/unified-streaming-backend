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
        providers = db.scalars(select(PlatformProvider).where(PlatformProvider.platform_id == platform.id)).all()
        companies = db.scalars(select(PlatformCompany).where(
            PlatformCompany.platform_id == platform.id, PlatformCompany.include_in_discovery.is_(True))).all()
        networks = db.scalars(select(PlatformNetwork).where(
            PlatformNetwork.platform_id == platform.id, PlatformNetwork.include_in_discovery.is_(True))).all()
        return platform, profile, rows, providers, companies, networks

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

    async def _query_row(self, row, profile, providers, companies, networks, page: int):
        region = profile.region_code if profile else "ZA"
        params: dict[str, Any] = {"page": page, "include_adult": "false", "region": region}
        if profile:
            params["language"] = profile.language
        provider_ids = [p.external_id for p in providers if p.provider_kind == "watch_provider" and (not p.region_code or p.region_code == region)]
        company_ids = [c.tmdb_company_id for c in companies]
        network_ids = [n.tmdb_network_id for n in networks]

        if provider_ids and row.strategy.startswith("provider_"):
            params["with_watch_providers"] = "|".join(map(str, provider_ids))
            params["watch_region"] = region
            params["with_watch_monetization_types"] = "flatrate"
        if company_ids and row.strategy.startswith("company_"):
            params["with_companies"] = "|".join(map(str, company_ids))
        if network_ids and row.strategy.startswith("network_"):
            params["with_networks"] = "|".join(map(str, network_ids))
        if row.genre_ids:
            params["with_genres"] = "|".join(str(x) for x in row.genre_ids)

        types = ["movie", "tv"] if row.media_scope == "mixed" else [row.media_scope]
        items = []
        total_pages = 1
        for media_type in types:
            if row.strategy == "trending":
                payload = await self.tmdb.trending(media_type, "week", page)
            else:
                sort_by = {
                    "provider_recent": "primary_release_date.desc",
                    "company_recent": "primary_release_date.desc",
                    "network_recent": "first_air_date.desc",
                    "popular": "popularity.desc",
                    "provider_popular": "popularity.desc",
                    "company_popular": "popularity.desc",
                    "network_popular": "popularity.desc",
                    "provider_genre": "popularity.desc",
                    "company_genre": "popularity.desc",
                    "network_genre": "popularity.desc",
                    "top_rated": "vote_average.desc",
                }.get(row.strategy, "popularity.desc")
                local_params = dict(params)
                local_params["sort_by"] = sort_by
                if row.strategy == "top_rated":
                    local_params["vote_count.gte"] = 100
                if row.strategy in {"provider_recent", "company_recent"} and media_type == "movie":
                    local_params["primary_release_date.lte"] = date.today().isoformat()
                payload = await self.tmdb.discover(media_type, local_params)
            total_pages = max(total_pages, int(payload.get("total_pages") or 1))
            for item in payload.get("results", []):
                if row.media_scope == "mixed":
                    item = {**item, "media_type": media_type}
                items.append(self._card(item, media_type))

        unique, seen = [], set()
        for item in items:
            key = (item.tmdb_id, item.media_type)
            if key not in seen:
                unique.append(item)
                seen.add(key)
        return unique[:row.page_size], page < total_pages

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
