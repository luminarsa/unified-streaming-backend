
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

    # Redis
    redis_url: str = "redis://red-dbub4i0m7kps73bsb63g:6379"

    # PayPal
    paypal_environment: str = "sandbox"
    paypal_client_id: str = "BAAkOCt7bqHguWccAM0613fyP58PaxVMf9pp_nNS-Mlsc2B0gRGDtaal1WR9AVZOogv-1B3fPR4sKtCzM8"
    paypal_client_secret: str = "EMVwxlAPZzShVbIQeoGomMW0XDzIwGKqez7xXN29XM5HgueSN29jfQvXIihVxqL7u2rP66a-AToA0NeT"
    paypal_webhook_id: str = ""
    paypal_api_timeout_seconds: float = 30.0

    # PayPal Invoicer Details
    paypal_invoicer_name: str = "Lumina"
    paypal_invoicer_email: str = ""
    paypal_business_name: str = "Lumina"
    paypal_business_phone: str = ""

    # Business address used on PayPal invoices
    paypal_business_address_line_1: str = ""
    paypal_business_address_line_2: str = ""
    paypal_business_city: str = ""
    paypal_business_state: str = ""
    paypal_business_postal_code: str = ""
    paypal_business_country_code: str = "ZA"

    # AES-256 encryption key for payment tokens.
    # Generate this once and keep it in your .env file.
    payment_encryption_key: str = "qRTk8DYfz3tQweQg1kx2Mpe/N4MK/5OQkdeW0HVHQ+M="

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()


import logging

import redis
from redis.exceptions import RedisError

from app.core.config import settings


logger = logging.getLogger(__name__)
