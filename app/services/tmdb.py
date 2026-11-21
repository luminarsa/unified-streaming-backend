
import httpx
import logging

from fastapi import HTTPException
from app.core.config import settings


logger = logging.getLogger(__name__)


class TMDBError(RuntimeError):
    pass


class TMDBClient:

    def __init__(self):
        if not settings.tmdb_api_read_access_token:
            raise HTTPException(
                status_code=503,
                detail="TMDB API token is not configured.",
            )

        self.base_url = settings.tmdb_api_base.rstrip("/")
        self.headers = {
            "Authorization": (
                f"Bearer {settings.tmdb_api_read_access_token}"
            ),
            "Accept": "application/json",
        }
        self.timeout = settings.tmdb_timeout_seconds

    # ---------------------------------------------------------
    # CORE HTTP REQUEST
    # ---------------------------------------------------------

    async def get(
        self,
        endpoint: str,
        params: dict | None = None,
    ) -> dict:

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=self.timeout,
            ) as client:

                response = await client.get(
                    endpoint,
                    params=params,
                )

                logger.info(
                    "TMDB REQUEST: %s",
                    response.request.url,
                )

                logger.info(
                    "TMDB STATUS: %s",
                    response.status_code,
                )

                response.raise_for_status()

                data = response.json()

                if not isinstance(data, dict):
                    raise TMDBError(
                        "TMDB returned an unexpected response format."
                    )

                logger.info(
                    "TMDB RESULTS: endpoint=%s, total_results=%s, "
                    "total_pages=%s, returned=%s",
                    endpoint,
                    data.get("total_results"),
                    data.get("total_pages"),
                    len(data.get("results", [])),
                )

                return data

        except httpx.TimeoutException as exc:
            logger.error(
                "TMDB TIMEOUT: endpoint=%s error=%s",
                endpoint,
                str(exc),
            )

            raise TMDBError(
                "TMDB request timed out."
            ) from exc

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code

            logger.error(
                "TMDB HTTP ERROR: endpoint=%s status=%s response=%s",
                endpoint,
                status_code,
                exc.response.text[:1000],
            )

            if status_code == 401:
                detail = "TMDB rejected the configured API token."
            elif status_code == 429:
                detail = "TMDB rate limit reached."
            else:
                detail = (
                    f"TMDB returned HTTP {status_code}."
                )

            raise TMDBError(detail) from exc

        except httpx.RequestError as exc:
            logger.error(
                "TMDB CONNECTION ERROR: endpoint=%s error=%s",
                endpoint,
                str(exc),
            )

            raise TMDBError(
                "Unable to connect to TMDB."
            ) from exc

    # ---------------------------------------------------------
    # DISCOVER MOVIES AND TV SHOWS
    # ---------------------------------------------------------

    async def discover(
        self,
        media_type: str,
        params: dict | None = None,
    ) -> dict:

        if media_type not in ("movie", "tv"):
            raise ValueError(
                "media_type must be either 'movie' or 'tv'."
            )

        return await self.get(
            f"/discover/{media_type}",
            params=params,
        )

    # ---------------------------------------------------------
    # TRENDING CONTENT
    # ---------------------------------------------------------

    async def trending(
        self,
        media_type: str,
        window: str = "week",
        page: int = 1,
    ) -> dict:

        if media_type not in ("movie", "tv", "all"):
            raise ValueError(
                "media_type must be movie, tv, or all."
            )

        if window not in ("day", "week"):
            raise ValueError(
                "window must be day or week."
            )

        return await self.get(
            f"/trending/{media_type}/{window}",
            params={"page": page},
        )

    # ---------------------------------------------------------
    # MOVIE DETAILS
    # ---------------------------------------------------------

    async def movie_details(self, tmdb_id: int) -> dict:
        return await self.get(
            f"/movie/{tmdb_id}"
        )

    # ---------------------------------------------------------
    # TV DETAILS
    # ---------------------------------------------------------

    async def tv_details(self, tmdb_id: int) -> dict:
        return await self.get(
            f"/tv/{tmdb_id}"
        )

    # ---------------------------------------------------------
    # GENERIC CONTENT DETAILS
    # ---------------------------------------------------------

    async def content_details(
        self,
        media_type: str,
        tmdb_id: int,
    ) -> dict:

        if media_type not in ("movie", "tv"):
            raise ValueError(
                "media_type must be movie or tv."
            )

        return await self.get(
            f"/{media_type}/{tmdb_id}"
        )

    # ---------------------------------------------------------
    # WATCH PROVIDERS
    # ---------------------------------------------------------

    async def watch_providers(
        self,
        media_type: str,
        watch_region: str | None = None,
    ) -> dict:

        if media_type not in ("movie", "tv"):
            raise ValueError(
                "media_type must be movie or tv."
            )

        params = {}

        if watch_region:
            params["watch_region"] = watch_region

        return await self.get(
            f"/watch/providers/{media_type}",
            params=params,
        )

    # ---------------------------------------------------------
    # CONTENT WATCH PROVIDERS
    # ---------------------------------------------------------

    async def content_watch_providers(
        self,
        media_type: str,
        tmdb_id: int,
    ) -> dict:

        if media_type not in ("movie", "tv"):
            raise ValueError(
                "media_type must be movie or tv."
            )

        return await self.get(
            f"/{media_type}/{tmdb_id}/watch/providers"
        )

    # ---------------------------------------------------------
    # CHECK PROVIDER AVAILABILITY
    # ---------------------------------------------------------

    @staticmethod
    def is_available_on_provider(
        provider_data: dict,
        provider_id: int,
        region: str,
        monetization_types: tuple = ("flatrate",),
    ) -> bool:

        results = provider_data.get("results", {})
        region_data = results.get(region, {})

        for monetization_type in monetization_types:

            providers = region_data.get(
                monetization_type,
                [],
            )

            for provider in providers:

                if provider.get("provider_id") == provider_id:
                    return True

        return False
