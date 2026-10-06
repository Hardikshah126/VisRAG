"""Optional API-key check and a small in-memory per-IP rate limiter."""

import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

import config


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """No-op unless API_KEY is configured."""
    if config.API_KEY is None:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


class RateLimiter:
    """Sliding-window limiter keyed by (bucket, client IP). Single process only;
    put a real limiter in front of the app for multi-worker deployments."""

    def __init__(self) -> None:
        self._hits: dict = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str, client: str, limit: int, window: float = 60.0) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        key = (bucket, client)
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                retry = max(1, int(window - (now - hits[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please slow down.",
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory under many distinct IPs
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] > window]:
                    del self._hits[stale]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_upload(request: Request) -> None:
    limiter.check("upload", _client_ip(request), config.RATE_LIMIT_UPLOAD_PER_MIN)


def limit_ask(request: Request) -> None:
    limiter.check("ask", _client_ip(request), config.RATE_LIMIT_ASK_PER_MIN)
