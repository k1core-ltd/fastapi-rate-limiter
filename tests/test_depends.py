import asyncio

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import HTTPConnection
from starlette.responses import Response

from fastapi_rate_limiter import RateLimiter, RateLimiterBackend, WebSocketRateLimiter
from tests.conftest import FakeRedis, http_request, websocket


def test_the_window_is_summed_from_its_parts() -> None:
    limiter = RateLimiter(times=2, hours=1, minutes=30, seconds=15, milliseconds=500)

    assert limiter.window_ms == 5_415_500


def test_a_limit_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="times"):
        RateLimiter(times=0, seconds=60)


def test_a_window_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="window"):
        RateLimiter(times=5)


def test_the_key_carries_the_caller_and_the_limit() -> None:
    limiter = RateLimiter(times=5, seconds=60)

    key = asyncio.run(limiter.key_for(http_request()))

    assert key == "rate-limit:203.0.113.7:/resend:5:60000"


def test_a_custom_identifier_replaces_the_default() -> None:
    async def by_tenant(connection: HTTPConnection) -> str:
        return "tenant-7"

    limiter = RateLimiter(times=1, seconds=60, identifier=by_tenant)

    assert asyncio.run(limiter.key_for(http_request())) == "rate-limit:tenant-7:1:60000"


def test_a_caller_that_asks_too_often_is_turned_away() -> None:
    redis = FakeRedis(0, 1_500)
    limiter = RateLimiter(times=1, seconds=60)

    async def _check() -> HTTPException:
        await RateLimiterBackend.setup(redis)

        await limiter(http_request(), Response())

        with pytest.raises(HTTPException) as error:
            await limiter(http_request(), Response())

        return error.value

    turned_away = asyncio.run(_check())

    assert turned_away.status_code == 429
    # part of a second left still costs a whole one
    assert turned_away.headers["Retry-After"] == "2"
    assert redis.keys == ["rate-limit:203.0.113.7:/resend:1:60000"] * 2


def test_callers_are_counted_apart() -> None:
    redis = FakeRedis(0, 0)
    limiter = RateLimiter(times=1, seconds=60)

    async def _ask_twice() -> None:
        await RateLimiterBackend.setup(redis)

        await limiter(http_request("203.0.113.7"), Response())
        await limiter(http_request("198.51.100.4"), Response())

    asyncio.run(_ask_twice())

    assert redis.keys == [
        "rate-limit:203.0.113.7:/resend:1:60000",
        "rate-limit:198.51.100.4:/resend:1:60000",
    ]


def test_a_request_that_gets_through_learns_when_the_window_resets() -> None:
    limiter = RateLimiter(times=3, seconds=60)
    request = http_request()
    response = Response()

    async def _ask() -> None:
        await RateLimiterBackend.setup(FakeRedis(ttl=30_000))

        await limiter(request, response)

    asyncio.run(_ask())

    assert request.state.rate_limit_reset_in_seconds == 30
    assert response.headers["X-RateLimit-Limit"] == "3"


def test_a_websocket_counts_each_context_apart() -> None:
    redis = FakeRedis()
    limiter = WebSocketRateLimiter(times=1, seconds=60)

    async def _ask() -> None:
        await RateLimiterBackend.setup(redis)

        await limiter(websocket(), context_key="room-1")
        await limiter(websocket(), context_key="room-2")

    asyncio.run(_ask())

    assert redis.keys == [
        "rate-limit:203.0.113.7:/ws:1:60000:room-1",
        "rate-limit:203.0.113.7:/ws:1:60000:room-2",
    ]
