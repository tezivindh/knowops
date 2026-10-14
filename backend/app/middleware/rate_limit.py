"""Shared Redis fixed-window limits; never trust forwarded client IP headers."""

import hashlib
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


class RateLimiter:
    def __init__(self, url: str) -> None:
        self.redis: Redis = Redis.from_url(
            url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True
        )

    async def allow(self, peer: str, category: str, limit: int) -> bool:
        digest = hashlib.sha256(peer.encode()).hexdigest()
        count = await cast(
            Awaitable[str],
            self.redis.eval(_SCRIPT, 1, f"knowops:limit:{category}:{digest}", "60"),
        )
        return int(count) <= limit

    async def close(self) -> None:
        await self.redis.aclose()
