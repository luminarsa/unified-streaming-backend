
import logging

import redis
from redis.exceptions import RedisError

from app.core.config import settings


logger = logging.getLogger(__name__)


redis_client = None

if settings.redis_url:
    redis_client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
    )


def get_redis_client():

    if redis_client is None:
        raise RuntimeError("Redis is not configured.")

    return redis_client


def check_redis_connection():

    if not settings.redis_url:
        logger.error("REDIS_URL environment variable is missing.")
        return {
            "connected": False,
            "reason": "REDIS_URL is missing from application settings."
        }

    if redis_client is None:
        return {
            "connected": False,
            "reason": "Redis client was not initialized."
        }

    try:
        redis_client.ping()

        return {
            "connected": True,
            "reason": "Redis PING successful."
        }

    except Exception as error:
        logger.exception("Redis connection failed.")

        return {
            "connected": False,
            "reason": str(error),
            "error_type": type(error).__name__
        }
