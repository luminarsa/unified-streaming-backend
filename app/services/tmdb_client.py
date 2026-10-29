
import httpx
from fastapi import HTTPException
from app.core.config import settings


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
            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504,
                detail="TMDB request timed out.",
            )

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code

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

        except httpx.RequestError:
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