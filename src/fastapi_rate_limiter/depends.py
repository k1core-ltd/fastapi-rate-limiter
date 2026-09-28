import math

from starlette.exceptions import HTTPException
from starlette.requests import HTTPConnection, Request
from starlette.responses import Response
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
from starlette.websockets import WebSocket

from fastapi_rate_limiter.backend import Identifier, RateLimiterBackend


class BaseRateLimiter:
    def __init__(
        self,
        times: int = 1,
        milliseconds: int = 0,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        identifier: Identifier | None = None,
    ) -> None:
        window_ms = milliseconds + 1000 * seconds + 60_000 * minutes + 3_600_000 * hours
        if times < 1:
            raise ValueError("times has to be at least 1")
        if window_ms < 1:
            raise ValueError("the window has to be at least one millisecond")

        self.times = times
        self.window_ms = window_ms
        self.identifier = identifier

    async def key_for(self, connection: HTTPConnection) -> str:
        identifier = self.identifier or RateLimiterBackend.identifier
        caller = await identifier(connection)
        return f"{RateLimiterBackend.prefix}:{caller}:{self.times}:{self.window_ms}"

    async def spend(self, key: str) -> None:
        retry_after_ms = await RateLimiterBackend.count(key, self.times, self.window_ms)
        if retry_after_ms:
            raise HTTPException(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                detail="Too Many Requests",
                headers={"Retry-After": str(math.ceil(retry_after_ms / 1000))},
            )


class RateLimiter(BaseRateLimiter):
    async def __call__(self, request: Request, response: Response) -> None:
        key = await self.key_for(request)
        await self.spend(key)

        reset_in_ms = await RateLimiterBackend.reset_in_ms(key)
        request.state.rate_limit_reset_in_seconds = math.ceil(reset_in_ms / 1000)
        response.headers["X-RateLimit-Limit"] = str(self.times)


class WebSocketRateLimiter(BaseRateLimiter):
    async def __call__(self, websocket: WebSocket, context_key: str = "") -> None:
        key = await self.key_for(websocket)
        if context_key:
            key = f"{key}:{context_key}"
        await self.spend(key)
