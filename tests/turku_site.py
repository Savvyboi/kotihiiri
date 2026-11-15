"""A fake paatokset.turku.fi API served from tests/fixtures/turku, for adapter and crawl tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from kunta.http import PoliteClient, RateLimiter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "turku"
UA = "KuntaDataBot/0.1 (+https://example.org/tietoa; test@example.org)"
SPA = "<!doctype html><html><body><div id=root></div></body></html>"  # robots.txt answers this


class FakeTurku:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.status: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = request.url.query.decode()
        full = path + (f"?{query}" if query else "")
        self.requests.append(full)
        if full in self.status:
            return httpx.Response(self.status[full])
        if path == "/robots.txt":
            return httpx.Response(200, text=SPA, headers={"Content-Type": "text/html; charset=utf-8"})
        name = None
        if path == "/api/toimielimet":
            name = "toimielimet.json"
        elif path == "/api/toimielin/Kv/paatosvuodet":
            name = "paatosvuodet-Kv.json"
        elif path == "/api/toimielin/Kv" and query.startswith("vuosi="):
            name = f"toimielin-Kv-{query[6:]}.json"
        elif path.startswith("/api/toimielin/") and path.endswith("/paatosvuodet"):
            return self._json([])
        elif path.startswith("/api/poytakirja/"):
            name = f"poytakirja-{path.rsplit('/', 1)[1]}.json"
        elif path.startswith("/api/lasnaolotiedot/"):
            name = f"lasnaolotiedot-{path.rsplit('/', 1)[1]}.json"
        elif path.startswith("/api/liitteet/"):
            name = f"liitteet-{path.rsplit('/', 1)[1]}.json"
            if not (FIXTURES / name).exists():
                return self._json({})
        elif path.startswith("/doc/2531451/"):
            pdf = (FIXTURES / "vote-2531451.pdf").read_bytes()
            return httpx.Response(200, content=pdf, headers={"Content-Type": "application/pdf"})
        if name and (FIXTURES / name).exists():
            return self._json(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
        if path.startswith(("/api/poytakirja/", "/api/lasnaolotiedot/")):
            return httpx.Response(404)
        if path.startswith("/api/"):
            return self._json([])  # other years and bodies: nothing
        return httpx.Response(404)

    @staticmethod
    def _json(obj) -> httpx.Response:
        return httpx.Response(200, json=obj)


def client(site: FakeTurku) -> PoliteClient:
    return PoliteClient(
        UA,
        transport=httpx.MockTransport(site),
        rate_limiter=RateLimiter(interval_s=0.0, sleep=lambda s: None),
        sleep=lambda s: None,
        allowed_hosts={"paatokset.turku.fi"},
    )
