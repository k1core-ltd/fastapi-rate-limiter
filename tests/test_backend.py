import asyncio

import pytest

from fastapi_rate_limiter import RateLimiterBackend, client_ip_and_path
from tests.conftest import FakeRedis, ForgetfulRedis, http_request


def test_counting_before_setup_is_refused() -> None:
    with pytest.raises(RuntimeError, match="setup"):
        asyncio.run(RateLimiterBackend.count("key", times=1, window_ms=1000))


def test_a_forgotten_script_is_loaded_again() -> None:
    redis = ForgetfulRedis()

    async def _count() -> int:
        await RateLimiterBackend.setup(redis)

        return await RateLimiterBackend.count("key", times=5, window_ms=1000)

    assert asyncio.run(_count()) == 0
    assert redis.loads == 2


def test_the_caller_is_taken_from_the_forwarded_header() -> None:
    caller = asyncio.run(client_ip_and_path(http_request("203.0.113.7", "/resend")))

    assert caller == "203.0.113.7:/resend"


def test_only_the_first_forwarded_address_counts() -> None:
    request = http_request("203.0.113.7, 198.51.100.4, 10.0.0.1")

    assert asyncio.run(client_ip_and_path(request)) == "203.0.113.7:/resend"


def test_the_caller_falls_back_to_the_socket_address() -> None:
    request = http_request(address=None)

    assert asyncio.run(client_ip_and_path(request)) == "10.0.0.1:/resend"


def test_a_caller_without_an_address_is_still_counted() -> None:
    request = http_request(address=None, connected=False)

    assert asyncio.run(client_ip_and_path(request)) == "unknown:/resend"


def test_the_window_of_an_unknown_key_resets_at_once() -> None:
    async def _reset() -> int:
        await RateLimiterBackend.setup(FakeRedis(ttl=-2))

        return await RateLimiterBackend.reset_in_ms("key")

    assert asyncio.run(_reset()) == 0
