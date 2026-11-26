"""Shared lazy Redis connection; startup does not require Redis availability."""
import redis

from app.config import settings

r = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)


def redis_healthy() -> bool:
    """Check dependency availability without exposing connection credentials."""
    try:
        return bool(r.ping())
    except redis.exceptions.RedisError:
        return False
