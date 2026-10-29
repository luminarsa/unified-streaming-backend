from typing import Any
import httpx
from app.core.config import settings

class TMDBError(RuntimeError):
    pass

class TMDBClient:
    def __init__(self):
        self.base_url = settings.tmdb_api_base.rstrip("/")

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not settings.tmdb_api_read_access_token:
            raise TMDBError("TMDB_API_READ_ACCESS_TOKEN is not configured")
        headers = {"Authorization": f"Bearer {settings.tmdb_api_read_access_token}", "accept": "application/json"}
        query = {"language": settings.tmdb_language, **(params or {})}
        try:
            async with httpx.AsyncClient(timeout=settings.tmdb_timeout_seconds) as client:
                response = await client.get(f"{self.base_url}{path}", params=query, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise TMDBError("TMDB request failed") from exc

    async def trending(self, media_type: str, window: str = "week", page: int = 1):
        if media_type not in {"movie", "tv", "all"} or window not in {"day", "week"}:
            raise ValueError("Invalid trending request")
        return await self.get(f"/trending/{media_type}/{window}", {"page": page})

    async def discover(self, media_type: str, params: dict[str, Any]):
        if media_type not in {"movie", "tv"}:
            raise ValueError("media_type must be movie or tv")
        return await self.get(f"/discover/{media_type}", params)
