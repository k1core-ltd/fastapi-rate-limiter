from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from redis.exceptions import NoScriptError
from starlette.requests import HTTPConnection

COUNT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window_ms = ARGV[2]

local current = tonumber(redis.call('GET', key) or "0")
if current >= limit then
    return redis.call('PTTL', key)
end

if current == 0 then
    redis.call('SET', key, 1, 'PX', window_ms)
else
    redis.call('INCR', key)
end
return 0
"""

Identifier = Callable[[HTTPConnection], Awaitable[str]]


async def client_ip_and_path(connection: HTTPConnection) -> str:
    forwarded = connection.headers.get("X-Forwarded-For")
    if forwarded:
        host = forwarded.split(",")[0].strip()
    elif connection.client is not None:
        host = connection.client.host
    else:
        host = "unknown"
    return f"{host}:{connection.scope['path']}"


class RateLimiterBackend:
    redis: Redis | None = None
    prefix: str = "rate-limit"
    identifier: Identifier = client_ip_and_path
    _script_sha: str | None = None

    @classmethod
    async def setup(
        cls,
        redis: Redis,
        prefix: str = "rate-limit",
        identifier: Identifier | None = None,
    ) -> None:
        cls.redis = redis
        cls.prefix = prefix
        cls.identifier = identifier or client_ip_and_path
        cls._script_sha = await redis.script_load(COUNT_SCRIPT)

    @classmethod
    async def close(cls) -> None:
        cls.redis = None
        cls._script_sha = None

    @classmethod
    async def count(cls, key: str, times: int, window_ms: int) -> int:
        if cls.redis is None or cls._script_sha is None:
            raise RuntimeError(
                "RateLimiterBackend.setup() has to run before the first request, "
                "usually from the lifespan of the application.",
            )

        try:
            return await cls.redis.evalsha(cls._script_sha, 1, key, str(times), str(window_ms))
        except NoScriptError:
            cls._script_sha = await cls.redis.script_load(COUNT_SCRIPT)
            return await cls.redis.evalsha(cls._script_sha, 1, key, str(times), str(window_ms))

    @classmethod
    async def reset_in_ms(cls, key: str) -> int:
        if cls.redis is None:
            return 0
        return max(await cls.redis.pttl(key), 0)
