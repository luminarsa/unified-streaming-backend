
import httpx
import logging

from fastapi import HTTPException
from app.core.config import settings


logger = logging.getLogger(__name__)


class TMDBClient:
    def __init__(self):
        if not settings.tmdb_api_read_access_token:
            raise HTTPException(
                status_code=503,
                detail="TMDB API token is not configured.",
            )

        self.client = httpx.Client(
            base_url=settings.tmdb_api_base.rstrip("/"),
            headers={
                "Authorization": (
                    f"Bearer {settings.tmdb_api_read_access_token}"
                ),
                "Accept": "application/json",
            },
            timeout=settings.tmdb_timeout_seconds,
        )

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        try:
            response = self.client.get(endpoint, params=params)

            # TEMPORARY DEBUG LOGGING
            print("========== TMDB CLIENT GET WAS CALLED ==========")
            logger.info("TMDB REQUEST: %s", response.request.url)
            logger.info("TMDB STATUS: %s", response.status_code)

            response.raise_for_status()

            data = response.json()

            logger.info(
                "TMDB RESULTS: endpoint=%s, total_results=%s, "
                "total_pages=%s, returned=%s",
                endpoint,
                data.get("total_results"),
                data.get("total_pages"),
                len(data.get("results", [])),
            )

            return data

        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504,
                detail="TMDB request timed out.",
            )

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code

            logger.error(
                "TMDB ERROR: status=%s, response=%s",
                status_code,
                exc.response.text[:1000],
            )

            if status_code == 401:
                detail = "TMDB rejected the configured API token."
            elif status_code == 429:
                detail = "TMDB rate limit reached. Please try again shortly."
            else:
                detail = "TMDB returned an error while fetching content."

            raise HTTPException(
                status_code=502,
                detail=detail,
            )

        except httpx.RequestError as exc:
            logger.error("TMDB CONNECTION ERROR: %s", str(exc))

            raise HTTPException(
                status_code=502,
                detail="Unable to connect to TMDB.",
            )

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
