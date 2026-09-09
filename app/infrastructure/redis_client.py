from redis.asyncio import Redis

from app.config import get_settings

_settings = get_settings()

# decode_responses=True returns str instead of bytes, which keeps stream and
# rate-limiter code free of .decode() calls later.
redis_client: Redis = Redis.from_url(_settings.redis_url, decode_responses=True)
