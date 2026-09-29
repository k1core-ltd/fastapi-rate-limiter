from collections.abc import Iterator

import pytest
from redis.exceptions import NoScriptError
from starlette.requests import Request
from starlette.websockets import WebSocket

from fastapi_rate_limiter import RateLimiterBackend, client_ip_and_path


class FakeRedis:
    def __init__(self, *milliseconds_left: int, ttl: int = 42_000) -> None:
        self.milliseconds_left = list(milliseconds_left)
        self.ttl = ttl
        self.keys: list[str] = []
        self.loads = 0

    async def script_load(self, script: str) -> str:
        self.loads += 1

        return f"sha-{self.loads}"

    async def evalsha(self, script_sha: str, key_count: int, key: str, *_: str) -> int:
        self.keys.append(key)

        return self.milliseconds_left.pop(0) if self.milliseconds_left else 0

    async def pttl(self, key: str) -> int:
        return self.ttl


class ForgetfulRedis(FakeRedis):
    async def evalsha(self, script_sha: str, key_count: int, key: str, *args: str) -> int:
        if self.loads == 1:
            raise NoScriptError("NOSCRIPT No matching script")

        return await super().evalsha(script_sha, key_count, key, *args)


def http_request(
    address: str | None = "203.0.113.7",
    path: str = "/resend",
    *,
    connected: bool = True,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"x-forwarded-for", address.encode())] if address else [],
            "client": ("10.0.0.1", 5000) if connected else None,
        },
    )


def websocket(address: str = "203.0.113.7", path: str = "/ws") -> WebSocket:
    async def _noop() -> dict:
        return {}

    return WebSocket(
        {
            "type": "websocket",
            "path": path,
            "headers": [(b"x-forwarded-for", address.encode())],
            "client": ("10.0.0.1", 5000),
        },
        receive=_noop,
        send=_noop,
    )


@pytest.fixture(autouse=True)
def _reset_the_backend() -> Iterator[None]:
    """The backend keeps its redis on the class, so tests would leak into each other."""
    yield

    RateLimiterBackend.redis = None
    RateLimiterBackend.prefix = "rate-limit"
    RateLimiterBackend.identifier = client_ip_and_path
    RateLimiterBackend._script_sha = None
