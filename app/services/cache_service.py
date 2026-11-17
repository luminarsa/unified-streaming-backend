

import json
import logging

from redis.exceptions import RedisError

from app.core.redis_client import get_redis_client


logger = logging.getLogger(__name__)


CACHE_PREFIX = "streaming_platform:"
DEFAULT_CACHE_TTL = 1800


def _build_cache_key(key: str) -> str:

    if not key or not isinstance(key, str):
        raise ValueError("Cache key must be a non-empty string.")

    return f"{CACHE_PREFIX}{key}"


def get_cache(key: str):
    """
    Retrieve data from Redis.

    Logs:
        CACHE HIT when data is found.
        CACHE MISS when data is not found.
    """

    try:
        client = get_redis_client()

        cache_key = _build_cache_key(key)

        cached_data = client.get(cache_key)

        if cached_data is None:

            logger.info(
                "CACHE MISS | key=%s",
                key,
            )

            return None

        logger.info(
            "CACHE HIT | key=%s",
            key,
        )

        return json.loads(cached_data)

    except (RedisError, RuntimeError, ValueError):
        logger.exception(
            "CACHE ERROR | Failed to retrieve key=%s",
            key,
        )

        return None

    except (json.JSONDecodeError, TypeError):
        logger.exception(
            "CACHE ERROR | Invalid cached JSON | key=%s",
            key,
        )

        return None


def set_cache(
    key: str,
    value,
    ttl: int = DEFAULT_CACHE_TTL
) -> bool:
    """
    Save data to Redis with an expiration time.

    Logs successful cache writes and failures.
    """

    try:
        if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0:
            raise ValueError("Cache TTL must be a positive integer.")

        client = get_redis_client()

        cache_key = _build_cache_key(key)

        serialized_data = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

        client.set(
            name=cache_key,
            value=serialized_data,
            ex=ttl,
        )

        logger.info(
            "CACHE SET | key=%s | ttl=%s seconds | items=%s",
            key,
            ttl,
            len(value) if isinstance(value, (list, dict)) else 1,
        )

        return True

    except (RedisError, RuntimeError, TypeError, ValueError):
        logger.exception(
            "CACHE ERROR | Failed to save key=%s",
            key,
        )

        return False


def delete_cache(key: str) -> bool:
    """
    Delete an individual cache entry.
    """

    try:
        client = get_redis_client()

        cache_key = _build_cache_key(key)

        deleted = client.delete(cache_key)

        if deleted:
            logger.info("CACHE DELETE | key=%s", key)

        return deleted > 0

    except (RedisError, RuntimeError, ValueError):
        logger.exception(
            "CACHE ERROR | Failed to delete key=%s",
            key,
        )

        return False


def cache_exists(key: str) -> bool:
    """
    Check whether a cache entry exists.
    """

    try:
        client = get_redis_client()

        cache_key = _build_cache_key(key)

        return bool(client.exists(cache_key))

    except (RedisError, RuntimeError, ValueError):
        logger.exception(
            "CACHE ERROR | Failed to check key=%s",
            key,
        )

        return False
