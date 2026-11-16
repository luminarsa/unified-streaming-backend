
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Unified Streaming Platform API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/streaming_demo"

    # TMDB
    tmdb_api_base: str = "https://api.themoviedb.org/3"
    tmdb_api_read_access_token: str = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJlZDE5Nzg1YTc2ZTA3ZWY1ZTgyMGY4ZDJmOTc5ZDI5YyIsIm5iZiI6MTcwMTczMTg5Ni44OTEsInN1YiI6IjY1NmU1ZTM4ODg2MzQ4MDBhZGU0YmVjZiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.s6KTNKs6pjyUKrt5p_VmaqHW1zZXHikmNzZyxCrTd10"
    tmdb_region: str = "US"
    tmdb_language: str = "en-US"
    tmdb_timeout_seconds: float = 40.0

    # PayPal
    paypal_environment: str = "sandbox"
    paypal_client_id: str = "BAAR-hvNWq567Is6LIOKZfL782WRWdYaMmCLosNnXtS6ChJuBuVr8GtogruZrtyR8S8mmhIJICLV1FDwJQ"
    paypal_client_secret: str = "EPeifxsZICwJVrREEOjcVai2yn_Z8FTg7nlRL2OsHK9wAbll9vYdnPrvoUtTGsFW-K10U94heRKnfC5P"
    paypal_webhook_id: str = "6JA85010LK1578833"
    paypal_api_timeout_seconds: float = 30.0

    # AES-256 encryption key for payment tokens.
    # Generate this once and keep it in your .env file.
    payment_encryption_key: str = "qRTk8DYfz3tQweQg1kx2Mpe/N4MK/5OQkdeW0HVHQ+M="

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()
