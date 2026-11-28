"""What every research tool shares: the result shape, HTTP with retries and throttling,
and the per-run cache and search log.

A tool never raises: a failure becomes a `ToolResult` with status "error", which the agent
turns into an escalation (spec 5.6). Nothing here guesses a value.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import SecretStr

RETRY_STATUS = {429, 500, 502, 503, 504}
ATTEMPTS = 3
BACKOFF_SECONDS = 1.0  # 1 s, then 2 s
MAX_PARALLEL_PER_PROVIDER = 4
TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests put recorded responses here

_throttles: dict[str, asyncio.Semaphore] = defaultdict(
    lambda: asyncio.Semaphore(MAX_PARALLEL_PER_PROVIDER)
)


@dataclass(frozen=True)
class ToolResult:
    """One tool call: what was asked, where the answer came from, when, and the answer."""

    tool: str  # e.g. "places_nearby"
    source: str  # the API or dataset, e.g. "Google Places API (New): searchNearby"
    query: dict[str, Any]  # the arguments, so the call can be cited and repeated
    retrieved_at: str  # ISO time in UTC
    status: Literal["ok", "empty", "error"]
    data: Any = None
    error: str = ""
    capped: bool = False  # the provider's result limit was hit: coverage is incomplete


def now() -> str:
    return datetime.now(UTC).isoformat()


def result(tool: str, source: str, query: dict[str, Any], data: Any, **kw: Any) -> ToolResult:
    return ToolResult(tool, source, query, now(), "ok" if data else "empty", data, **kw)


def failed(tool: str, source: str, query: dict[str, Any], error: str) -> ToolResult:
    return ToolResult(tool, source, query, now(), "error", None, error)


class ToolError(Exception):
    """The call failed after its retries, or could not be made (e.g. no key)."""


def key(secret: SecretStr | None, name: str) -> str:
    if secret is None or not secret.get_secret_value():
        raise ToolError(f"{name} is not set")
    return secret.get_secret_value()


async def request(
    provider: str, method: str, url: str, *, timeout: float, **kwargs: Any
) -> httpx.Response:
    """Send a request; retry timeouts, connection errors, 429 and 5xx (3 attempts, backoff).

    Returns any other response, including 4xx, for the caller to judge. Error messages never
    contain the URL, because Google Elevation puts the key in it.
    """
    reason = ""
    async with _throttles[provider]:
        for attempt in range(ATTEMPTS):
            if attempt:
                await asyncio.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
            try:
                async with httpx.AsyncClient(timeout=timeout, transport=TRANSPORT) as client:
                    r = await client.request(method, url, **kwargs)
            except httpx.TransportError as exc:  # timeouts and connection errors
                reason = type(exc).__name__
                continue
            if r.status_code not in RETRY_STATUS:
                return r
            reason = f"HTTP {r.status_code}"
    raise ToolError(f"{provider}: gave up after {ATTEMPTS} attempts ({reason})")


def ok_json(r: httpx.Response, provider: str) -> Any:
    if r.is_error:
        raise ToolError(f"{provider}: HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


@dataclass
class ToolRun:
    """One per phase run: identical calls are answered from the cache, and every call is
    logged, so an agent can say exactly what it searched and what came back."""

    cache: dict[str, ToolResult] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)

    async def call(self, tool: Callable[..., Awaitable[ToolResult]], **args: Any) -> ToolResult:
        cache_key = tool.__name__ + json.dumps(args, sort_keys=True, default=str)
        cached = cache_key in self.cache
        res = self.cache[cache_key] if cached else await tool(**args)
        if res.status != "error":  # a failure may succeed on the next try
            self.cache[cache_key] = res
        n = len(res.data) if isinstance(res.data, list) else int(res.data is not None)
        self.log.append(
            {
                "tool": res.tool,
                "query": res.query,
                "status": res.status,
                "n_results": n,
                "capped": res.capped,
                "cached": cached,
            }
        )
        return res
