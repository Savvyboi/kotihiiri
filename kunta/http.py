"""Polite HTTP client: robots.txt, per-host rate limit, retries, conditional GET, raw cache.

Adapters never talk to the network directly; they go through `PoliteClient`
(PLAN.md §2.1, §6). Rules enforced here:

- robots.txt is fetched once per host per run and checked for every URL with our
  User-Agent. Disallowed URLs are never fetched and are logged as `skipped_robots`.
- At most 1 request/second per host, one in-flight request per host.
- 429/5xx → exponential backoff honouring Retry-After, give up after 4 attempts.
- ETag / Last-Modified are remembered and sent back as conditional headers.
- Raw bodies go to `.cache/raw/` (git-ignored), never to data/.
"""

from __future__ import annotations

import email.utils
import hashlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import jsonio
from .robots import RobotsRules

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
MIN_INTERVAL_S = 1.0
# Hosts of one shared provider (*.oncloudos.com, *.cloudnc.fi, …) share a cap of 2 requests/second
# on top of the per-host 1/s (PLAN.md §18.2), until S12 shows they are separate backends.
PROVIDER_INTERVAL_S = 0.5
RETRY_STATUSES = {429, 500, 502, 503, 504}


class RobotsDisallowed(Exception):
    """Raised when robots.txt forbids a URL. The URL was not fetched."""


class FetchFailed(Exception):
    pass


class NotFound(FetchFailed):
    """404 or 410: the source removed the document."""


@dataclass
class Response:
    url: str
    status: int
    content: bytes
    headers: dict[str, str]
    from_cache: bool = False

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    @property
    def text(self) -> str:
        """Decode using the response charset; never assume (Espoo mixes encodings)."""
        ct = self.content_type.lower()
        charset = None
        if "charset=" in ct:
            charset = ct.split("charset=", 1)[1].split(";")[0].strip().strip('"')
        try:
            return self.content.decode(charset or "utf-8")
        except (LookupError, UnicodeDecodeError):
            return self.content.decode("iso-8859-1")


@dataclass
class Stats:
    requests: int = 0
    not_modified: int = 0
    skipped_robots: list[str] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)


def _default_provider(host: str) -> str:
    from .registry import provider_of

    return provider_of(host)


class RateLimiter:
    """Minimum interval between requests to the same host, one request at a time per host, and a
    shared minimum interval across the hosts of one provider (§18.2)."""

    def __init__(
        self,
        interval_s: float = MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        provider_interval_s: float = PROVIDER_INTERVAL_S,
        provider_of: Callable[[str], str] = _default_provider,
    ) -> None:
        self.interval_s = interval_s
        self.provider_interval_s = provider_interval_s
        self._provider_of = provider_of
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._last_provider: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock(self, host: str) -> threading.Lock:
        # One lock per provider: hosts sharing a provider take turns, so the shared cap holds
        # even when several hosts are fetched in parallel threads.
        key = self._provider_of(host)
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def wait(self, host: str) -> None:
        provider = self._provider_of(host)
        waits = []
        if (last := self._last.get(host)) is not None:
            waits.append(self.interval_s - (self._clock() - last))
        if provider != host and (last := self._last_provider.get(provider)) is not None:
            waits.append(self.provider_interval_s - (self._clock() - last))
        remaining = max(waits, default=0.0)
        if remaining > 0:
            self._sleep(remaining)
        now = self._clock()
        self._last[host] = now
        self._last_provider[provider] = now


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        *,
        cache_dir: Path | None = None,
        validators_path: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        rate_limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        allowed_hosts: set[str] | None = None,
    ) -> None:
        if not user_agent:
            raise ValueError("user_agent is required")
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self.validators_path = validators_path
        self.allowed_hosts = allowed_hosts
        self.rate = rate_limiter or RateLimiter(sleep=sleep)
        self._sleep = sleep
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            transport=transport,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
        )
        self._robots: dict[str, RobotsRules] = {}
        # Per host: how robots.txt answered (`ok`, `no_robots`, `forbidden`, `unreachable`), for the
        # robots audit (M10).
        self.robots_status: dict[str, str] = {}
        self.validators: dict[str, dict[str, str]] = {}
        if validators_path and validators_path.exists():
            self.validators = jsonio.read(validators_path)
        self.stats = Stats()

    # -- robots ---------------------------------------------------------------

    def _robots_for(self, scheme: str, host: str) -> RobotsRules:
        if host not in self._robots:
            rp = RobotsRules()
            robots_url = f"{scheme}://{host}/robots.txt"
            try:
                with self.rate.lock(host):
                    self.rate.wait(host)
                    resp = self._client.get(robots_url)
                self.stats.requests += 1
                if resp.status_code in (401, 403):
                    rp.disallow_all = True
                    self.robots_status[host] = "forbidden"
                elif resp.status_code >= 500:
                    # RFC 9309: a server error on robots.txt means assume complete disallow.
                    rp.disallow_all = True
                    self.robots_status[host] = "unreachable"
                elif resp.status_code >= 400:
                    rp.allow_all = True  # no robots.txt → everything allowed
                    self.robots_status[host] = "no_robots"
                else:
                    rp = RobotsRules(resp.text)
                    self.robots_status[host] = "ok"
            except httpx.HTTPError as exc:
                # Unreachable robots.txt: be conservative and fetch nothing from this host.
                log.warning("robots.txt unreachable for %s: %s", host, exc)
                rp.disallow_all = True
                self.robots_status[host] = "unreachable"
            self._robots[host] = rp
        return self._robots[host]

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        return self._robots_for(parts.scheme, parts.netloc).can_fetch(self.user_agent, url)

    # -- fetching -------------------------------------------------------------

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / urlsplit(url).netloc / digest[:2] / digest

    def get(self, url: str) -> Response:
        return self._request("GET", url)

    def post_json(self, url: str, body: object) -> Response:
        """POST a JSON query (PxWeb APIs). Same robots, rate and retry rules as `get`; never cached."""
        return self._request("POST", url, body)

    def _request(self, method: str, url: str, body: object = None) -> Response:
        parts = urlsplit(url)
        host = parts.netloc
        if self.allowed_hosts is not None and host not in self.allowed_hosts:
            raise FetchFailed(f"host {host} is not configured for this run")
        if not self.allowed(url):
            log.info("skipped_robots %s", url)
            self.stats.skipped_robots.append(url)
            raise RobotsDisallowed(url)

        headers: dict[str, str] = {}
        cache_path = self._cache_path(url) if method == "GET" else None
        known = self.validators.get(url, {})
        if cache_path and cache_path.exists():
            if etag := known.get("etag"):
                headers["If-None-Match"] = etag
            if last_mod := known.get("last_modified"):
                headers["If-Modified-Since"] = last_mod

        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            with self.rate.lock(host):
                self.rate.wait(host)
                try:
                    resp = self._client.request(method, url, headers=headers, json=body)
                except httpx.HTTPError as exc:
                    resp = None
                    last_error = f"{type(exc).__name__}: {exc}"
            self.stats.requests += 1

            if resp is not None and resp.status_code == 304 and cache_path:
                self.stats.not_modified += 1
                return Response(
                    url, 200, cache_path.read_bytes(), dict(known.get("headers", {})), from_cache=True
                )
            if resp is not None and resp.status_code not in RETRY_STATUSES:
                return self._finish(url, resp, cache_path)

            if resp is not None:
                last_error = f"HTTP {resp.status_code}"
            if attempt < MAX_ATTEMPTS:
                self._sleep(self._backoff(attempt, resp))

        self.stats.failures.append({"url": url, "error": last_error})
        raise FetchFailed(f"{url}: {last_error} after {MAX_ATTEMPTS} attempts")

    @staticmethod
    def _backoff(attempt: int, resp: httpx.Response | None) -> float:
        if resp is not None and (ra := resp.headers.get("retry-after")):
            if ra.strip().isdigit():
                return float(ra)
            when = email.utils.parsedate_to_datetime(ra)
            if when is not None:
                return max(0.0, when.timestamp() - time.time())
        return float(2**attempt)

    def _finish(self, url: str, resp: httpx.Response, cache_path: Path | None) -> Response:
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        keep = {k: hdrs[k] for k in ("content-type",) if k in hdrs}
        if resp.status_code == 200 and cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(resp.content)
            entry: dict = {"headers": keep}
            if "etag" in hdrs:
                entry["etag"] = hdrs["etag"]
            if "last-modified" in hdrs:
                entry["last_modified"] = hdrs["last-modified"]
            self.validators[url] = entry
        return Response(url, resp.status_code, resp.content, hdrs)

    def save_validators(self) -> None:
        if self.validators_path:
            jsonio.write(self.validators_path, self.validators)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.save_validators()
        self.close()
