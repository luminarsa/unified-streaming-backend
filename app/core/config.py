from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "Unified Streaming Platform API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/streaming_demo"
    tmdb_api_base: str = "https://api.themoviedb.org/3"
    tmdb_api_read_access_token: str = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJlZDE5Nzg1YTc2ZTA3ZWY1ZTgyMGY4ZDJmOTc5ZDI5YyIsIm5iZiI6MTcwMTczMTg5Ni44OTEsInN1YiI6IjY1NmU1ZTM4ODg2MzQ4MDBhZGU0YmVjZiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.s6KTNKs6pjyUKrt5p_VmaqHW1zZXHikmNzZyxCrTd10"
    tmdb_region: str = "ZA"
    tmdb_language: str = "en-US"
    tmdb_timeout_seconds: float = 40.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
