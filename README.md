# fastapi-rate-limiter-plugin

Redis backed rate limiting for FastAPI and Starlette, as a dependency on the
endpoints that need it.

## Install

```bash
pip install fastapi-rate-limiter-plugin
```

## Use

Point the backend at redis once, from the lifespan of the application:

```python
import contextlib

import redis.asyncio
from fastapi import Depends, FastAPI
from fastapi_rate_limiter import RateLimiter, RateLimiterBackend


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    await RateLimiterBackend.setup(redis.asyncio.from_url("redis://localhost"))
    yield
    await RateLimiterBackend.close()


app = FastAPI(lifespan=lifespan)


@app.post("/resend", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def resend() -> dict:
    return {"sent": True}
```

A caller over the limit gets a `429` with a `Retry-After` header. A request that
gets through leaves `request.state.rate_limit_reset_in_seconds`, so an endpoint
can tell the caller when the window resets.

Callers are told apart by `X-Forwarded-For`, falling back to the peer address,
together with the path. Pass `identifier` to `setup` or to a single limiter to
count by something else, such as a tenant or an API key:

```python
async def by_tenant(connection: HTTPConnection) -> str:
    return connection.headers.get("X-Tenant-Id", "unknown")


RateLimiter(times=100, hours=1, identifier=by_tenant)
```

## Websockets

`WebSocketRateLimiter` counts messages rather than connections, and takes a
context key so one socket can hold several independent limits:

```python
limiter = WebSocketRateLimiter(times=10, seconds=5)


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    while True:
        message = await websocket.receive_text()
        await limiter(websocket, context_key=message)
```

## Notes

Counting is a single Lua script, so a window is counted atomically and every
instance of the service counts one caller together. The script is reloaded by
itself when redis drops its cache after a restart.

## License

MIT
