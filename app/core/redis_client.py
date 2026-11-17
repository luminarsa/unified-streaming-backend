
import redis
from redis.exceptions import RedisError

from app.core.config import settings


# Create a Redis connection only when REDIS_URL is configured.
# The actual network connection happens when a command is executed.
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
    """
    Return the shared Redis client.

    Raises an error if Redis has not been configured.
    """

    if redis_client is None:
        raise RuntimeError(
            "Redis is not configured. Please set REDIS_URL."
        )

    return redis_client


def check_redis_connection() -> bool:
    """
    Check whether Redis is reachable.

    Returns True when the connection works,
    otherwise returns False.
    """

    if redis_client is None:
        return False

    try:
        return redis_client.ping()

    except RedisError:
        return False
