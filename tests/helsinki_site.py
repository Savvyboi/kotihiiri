"""A fake paatokset.hel.fi served from tests/fixtures/helsinki, for adapter and crawl tests."""

from __future__ import annotations

from pathlib import Path

import httpx

from kunta.http import PoliteClient, RateLimiter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "helsinki"
UA = "KuntaDataBot/0.1 (+https://example.org/tietoa; test@example.org)"

# The wildcard rules of the real robots.txt (2026-10-11), abridged.
ROBOTS = """\
User-agent: *
Disallow: /core/
Disallow: /admin/
Disallow: /search?
Disallow: /*?*from=*
Disallow: /*?*to=*
Disallow: /*?*category=*
Disallow: /*?*dm=*
Disallow: /fi/asia?*s=*
Disallow: /fi/paattajat?*s=*
"""
EMPTY_LISTING = "<html><body><main><h1>Asiakirjat</h1><p>0 asiakirjaa</p></main></body></html>"

MEETINGS = {
    "02900202615": "meeting-02900202615.html",
    "02900202614": "meeting-02900202614.html",
    "02900202613": "meeting-02900202614.html",
    "0290020251": "meeting-02900202614.html",
}


class FakeHelsinki:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.overrides: dict[str, str] = {}  # path → fixture file name
        self.status: dict[str, int] = {}  # path → HTTP status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = request.url.query.decode()
        full = path + (f"?{query}" if query else "")
        self.requests.append(full)
        if path in self.status:
            return httpx.Response(self.status[path])
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if path in self.overrides:
            return self._file(self.overrides[path])
        if path == "/fi/paattajat/lautakunnat-ja-johtokunnat":
            return self._file("lautakunnat-ja-johtokunnat.html")
        if path == "/fi/paattajat/kaupunginvaltuusto/asiakirjat" and query in ("page=0", "page=1"):
            return self._file(f"listing-kaupunginvaltuusto-{query[-1]}.html")
        if path.endswith("/asiakirjat"):
            return self._html(EMPTY_LISTING)
        if path.startswith("/fi/paattajat/kaupunginvaltuusto/asiakirjat/"):
            return self._file(MEETINGS[path.rsplit("/", 1)[1]])
        if path == "/fi/asia/hel-2026-008342":
            return self._file("item-hel-2026-008342.html")
        if path.startswith("/fi/asia/"):
            return self._file("item-roll-call.html")
        return httpx.Response(404)

    @staticmethod
    def _html(text: str) -> httpx.Response:
        return httpx.Response(200, text=text, headers={"Content-Type": "text/html; charset=UTF-8"})

    def _file(self, name: str) -> httpx.Response:
        return self._html((FIXTURES / name).read_text(encoding="utf-8"))


def client(site: FakeHelsinki) -> PoliteClient:
    return PoliteClient(
        UA,
        transport=httpx.MockTransport(site),
        rate_limiter=RateLimiter(interval_s=0.0, sleep=lambda s: None),
        sleep=lambda s: None,
        allowed_hosts={"paatokset.hel.fi"},
    )
