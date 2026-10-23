"""Safe outbound HTTP: SSRF checks on every hop, size caps, timeouts, robots.txt, bounded retries."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.security.validation import Resolver, UnsafeURLError, check_url_destination, system_resolve


class FetchError(Exception):
    pass


@dataclass
class FetchedDocument:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    retrieved_at: datetime

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class SafeFetcher:
    def __init__(
        self,
        user_agent: str,
        timeout_s: float = 15.0,
        max_bytes: int = 3_000_000,
        max_redirects: int = 3,
        max_attempts: int = 2,
        resolver: Resolver = system_resolve,
        allowed_hosts: set[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        respect_robots: bool = True,
    ):
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.max_attempts = max_attempts
        self.resolver = resolver
        self.allowed_hosts = allowed_hosts
        self.transport = transport
        self.respect_robots = respect_robots
        self._robots: dict[str, RobotFileParser | None] = {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout_s,
            follow_redirects=False,
            headers={"User-Agent": self.user_agent},
            transport=self.transport,
        )

    async def allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                doc = await self._fetch_once(origin + "/robots.txt", check_robots=False, max_bytes=200_000)
                if doc.status >= 400:
                    parser = None  # no robots file: allowed
                else:
                    parser.parse(doc.text.splitlines())
            except (FetchError, UnsafeURLError):
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    async def fetch(self, url: str, method: str = "GET", params: dict | None = None,
                    data: dict | None = None) -> FetchedDocument:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await self._fetch_once(url, method=method, params=params, data=data)
            except UnsafeURLError:
                raise
            except FetchError as exc:
                last_exc = exc
                if "HTTP 4" in str(exc):
                    break  # client errors are not retried
                await asyncio.sleep(min(0.5 * 2 ** (attempt - 1), 4))
        raise FetchError(str(last_exc))

    async def _fetch_once(self, url: str, method: str = "GET", params: dict | None = None,
                          data: dict | None = None, check_robots: bool = True,
                          max_bytes: int | None = None) -> FetchedDocument:
        limit = max_bytes or self.max_bytes
        current = url
        async with self._client() as client:
            for _ in range(self.max_redirects + 1):
                await check_url_destination(current, self.resolver, self.allowed_hosts)
                if check_robots and self.respect_robots and not await self.allowed_by_robots(current):
                    raise FetchError(f"robots.txt disallows {current}")
                try:
                    request = client.build_request(method, current, params=params, data=data)
                    response = await client.send(request, stream=True)
                except httpx.HTTPError as exc:
                    raise FetchError(f"{type(exc).__name__} fetching {current}") from exc
                try:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("Redirect without location")
                        current = urljoin(current, location)
                        method, data = "GET", None
                        continue
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > limit:
                            raise FetchError(f"Response exceeds {limit} bytes")
                    if response.status_code >= 400:
                        raise FetchError(f"HTTP {response.status_code} from {current}")
                    return FetchedDocument(
                        url=url,
                        final_url=current,
                        status=response.status_code,
                        content_type=response.headers.get("content-type", ""),
                        body=bytes(body),
                        retrieved_at=datetime.now(timezone.utc),
                    )
                finally:
                    await response.aclose()
        raise FetchError("Too many redirects")


class RateLimiter:
    """Simple per-host minimum interval (e.g. Nominatim: max 1 request/second)."""

    def __init__(self, min_interval_s: float):
        self.min_interval_s = min_interval_s
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            delta = time.monotonic() - self._last
            if delta < self.min_interval_s:
                await asyncio.sleep(self.min_interval_s - delta)
            self._last = time.monotonic()
