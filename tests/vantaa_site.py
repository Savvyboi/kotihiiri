"""A fake paatokset.vantaa.fi served from tests/fixtures/vantaa, for adapter and crawl tests."""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from kunta.http import PoliteClient, RateLimiter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vantaa"
UA = "KuntaDataBot/0.1 (+https://example.org/tietoa; test@example.org)"
ROBOTS = "User-agent: *\nDisallow: /ktwebscr/vparhaku_tweb.htm\n"
EMPTY_LIST = '<table><caption> Haetut kokoukset </caption><tr class="colheader"><th>x</th></tr></table>'
# Documents not recorded get the procedural item of their meeting's kind.
DEFAULT_DOC = "doc-3460153.pdf"


class FakeVantaa:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.status: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, query = request.url.path, request.url.query.decode()
        key = f"{path}?{query}" if query else path
        self.requests.append(key)
        if key in self.status:
            return httpx.Response(self.status[key])
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if path == "/ktwebscr/pk_tek_tweb.htm":
            return self._html("bodies.html")
        if m := re.fullmatch(r"\+kirjaamo=(\d+)", query):
            kind = "minutes" if path.endswith("pk_kokl_tweb.htm") else "agendas"
            name = f"{kind}-{m.group(1)}.html"
            return self._html(name) if (FIXTURES / name).exists() else self._text(EMPTY_LIST)
        if m := re.fullmatch(r"bid=(\d+)", query):
            name = ("meeting" if "pk_asil" in path else "agenda") + f"-{m.group(1)}.html"
            return self._html(name) if (FIXTURES / name).exists() else httpx.Response(404)
        if path.endswith("_attn_tweb.htm") and (m := re.fullmatch(r"\+?id=(\d+)", query)):
            name = f"attachments-{m.group(1)}.html"
            return self._html(name) if (FIXTURES / name).exists() else self._text(EMPTY_LIST)
        if path == "/ktwebscr/fileshow" and (m := re.search(r"docid=(\d+)", query)):
            name = f"doc-{m.group(1)}.pdf"
            data = (FIXTURES / (name if (FIXTURES / name).exists() else DEFAULT_DOC)).read_bytes()
            return httpx.Response(200, content=data, headers={"Content-Type": "application/pdf"})
        return httpx.Response(404)

    @staticmethod
    def _html(name: str) -> httpx.Response:
        return FakeVantaa._text((FIXTURES / name).read_text(encoding="utf-8"))

    @staticmethod
    def _text(text: str) -> httpx.Response:
        # The site declares ISO-8859-1; Windows-1252 also covers the en dashes it prints.
        return httpx.Response(
            200, content=text.encode("cp1252"), headers={"Content-Type": "text/html; charset=iso-8859-1"}
        )


def client(site: FakeVantaa) -> PoliteClient:
    return PoliteClient(
        UA,
        transport=httpx.MockTransport(site),
        rate_limiter=RateLimiter(interval_s=0.0, sleep=lambda s: None),
        sleep=lambda s: None,
        allowed_hosts={"paatokset.vantaa.fi"},
    )
