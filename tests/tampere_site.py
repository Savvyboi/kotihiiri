"""A fake tampere.cloudnc.fi served from tests/fixtures/tampere, for adapter and crawl tests."""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from kunta.http import PoliteClient, RateLimiter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tampere"
UA = "KuntaDataBot/0.1 (+https://example.org/tietoa; test@example.org)"
ROBOTS = "User-agent: SemrushBot\nDisallow: /\n\nUser-agent: *\nDisallow: /fi-FI/rss/*\n"
EMPTY_BODY = '<div id="contentAreaDiv"><h1 id="ContentStart">Toimielin</h1></div>'


class FakeTampere:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.status: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if path in self.status:
            return httpx.Response(self.status[path])
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if path == "/fi-FI/Toimielimet":
            return self._html("bodies.html")
        if m := re.fullmatch(r"/fi-FI/Toimielimet/([^/]+)", path):
            name = f"body-{m.group(1)}.html"
            return self._html(name) if (FIXTURES / name).exists() else self._text(EMPTY_BODY)
        if m := re.fullmatch(r"/fi-FI/Toimielimet/([^/]+)/(Kokous_\d+)", path):
            name = f"meeting-{m.group(1)}-{m.group(2)}.html"
            return self._html(name) if (FIXTURES / name).exists() else httpx.Response(404)
        if m := re.fullmatch(r"/fi-FI/content/(\d+)/(\d+)", path):
            name = f"item-{m.group(1)}-{m.group(2)}.html"
            if (FIXTURES / name).exists():
                return self._html(name)
            # items not recorded get the procedural page of their meeting's kind
            return self._html("item-522031-37342.html" if m.group(2) == "37342" else "item-476092-35325.html")
        return httpx.Response(404)

    @staticmethod
    def _html(name: str) -> httpx.Response:
        return FakeTampere._text((FIXTURES / name).read_text(encoding="utf-8"))

    @staticmethod
    def _text(text: str) -> httpx.Response:
        return httpx.Response(
            200, content=text.encode(), headers={"Content-Type": "text/html; charset=utf-8"}
        )


def client(site: FakeTampere) -> PoliteClient:
    return PoliteClient(
        UA,
        transport=httpx.MockTransport(site),
        rate_limiter=RateLimiter(interval_s=0.0, sleep=lambda s: None),
        sleep=lambda s: None,
        allowed_hosts={"tampere.cloudnc.fi"},
    )
