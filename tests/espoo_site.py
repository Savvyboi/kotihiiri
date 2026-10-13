"""A fake espoo.oncloudos.com served from tests/fixtures/espoo, for adapter and crawl tests."""

from __future__ import annotations

from pathlib import Path

import httpx

from kunta.http import PoliteClient, RateLimiter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "espoo"
UA = "KuntaDataBot/0.1 (+https://example.org/tietoa; test@example.org)"
ROBOTS = "User-agent: *\nDisallow: /cgi/admin\n"

MEETINGS = {"20261715", "20251553", "20261743"}
ITEMS = {"20261715-13", "20251553-3"}
PDFS = {"20261715-13-375914", "20251553-3-330209"}


class FakeEspoo:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.overrides: dict[str, tuple[str, bytes]] = {}  # path+query → (content type, body)
        self.status: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = request.url.query.decode()
        full = path + (f"?{query}" if query else "")
        self.requests.append(full)
        if full in self.status:
            return httpx.Response(self.status[full])
        if full in self.overrides:
            ct, body = self.overrides[full]
            return httpx.Response(200, content=body, headers={"Content-Type": ct})
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if path == "/cgi/DREQUEST.PHP":
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            kind, ident = params.get("page"), params.get("id", "")
            if kind == "meeting_frames":
                return self._latin1("meeting_frames.html")
            if kind == "meetings":
                return self._latin1("meetings-1.html" if ident == "1" else "meetings-empty.html")
            if kind == "meeting" and ident in MEETINGS:
                return self._utf8(f"meeting-{ident}.html")
            if kind == "meetingitem":
                mid = ident.split("-", 1)[0]
                if ident in ITEMS:
                    return self._utf8(f"item-{ident}.html")
                if mid == "20261743":
                    return self._utf8("item-agenda.html")
                return self._utf8("item-20261715-1.html")
        if path.startswith("/kokous/") and path.endswith(".PDF"):
            key = path[len("/kokous/") : -len(".PDF")]
            if key in PDFS:
                return httpx.Response(
                    200,
                    content=(FIXTURES / f"vote-{key}.pdf").read_bytes(),
                    headers={"Content-Type": "application/pdf"},
                )
        return httpx.Response(404)

    @staticmethod
    def _latin1(name: str) -> httpx.Response:
        # Listing pages are ISO-8859-1 and the header names no charset; the meta tag does.
        return httpx.Response(
            200, content=(FIXTURES / name).read_bytes(), headers={"Content-Type": "text/html"}
        )

    @staticmethod
    def _utf8(name: str) -> httpx.Response:
        return httpx.Response(
            200, content=(FIXTURES / name).read_bytes(), headers={"Content-Type": "text/html; charset=UTF-8"}
        )


def client(site: FakeEspoo) -> PoliteClient:
    return PoliteClient(
        UA,
        transport=httpx.MockTransport(site),
        rate_limiter=RateLimiter(interval_s=0.0, sleep=lambda s: None),
        sleep=lambda s: None,
        allowed_hosts={"espoo.oncloudos.com"},
    )
