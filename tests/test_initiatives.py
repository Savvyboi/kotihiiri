"""kuntalaisaloite.fi Open Data API reader (kunta/initiatives.py). Responses follow the shapes in the
service's API documentation (https://www.kuntalaisaloite.fi/api); names and texts are fictional."""

import json

import httpx
import pytest

from kunta import jsonio
from kunta.http import PoliteClient, RateLimiter, RobotsDisallowed
from kunta.initiatives import API, HOST, BotCheck, api_id, match_municipalities, run

UA = "KuntaDataBot/0.1 (+https://example.org/tietoa; test@example.org)"
ROBOTS = "User-agent: Googlebot\nDisallow: /fi/kirjaudu\n\nUser-agent: *\nDisallow: /\n"
EXC = {HOST: ("/api/v1/",)}


def muni(mid, fi, sv, active=True):
    return {"active": active, "id": f"{API}/municipalities/{mid}", "nameFi": fi, "nameSv": sv}


MUNIS = [
    muni(91, "Helsinki", "Helsingfors"),
    muni(49, "Espoo", "Esbo"),
    muni(5, "Alajärvi", "Alajärvi", False),
]


def entry(i, mid=91, sent=None, n=3):
    return {
        "collaborative": True,
        "id": f"{API}/initiatives/{i}",
        "municipality": MUNIS[0] if mid == 91 else MUNIS[1],
        "name": f"Aloite {i}",
        "participantCount": n,
        "publishDate": "2026-01-0" + str(i % 9 + 1),
        "sentTime": sent,
        "type": "COLLABORATIVE",
        "url": {"fi": f"https://{HOST}/fi/aloite/{i}", "sv": f"https://{HOST}/sv/initiativ/{i}"},
    }


def detail(i, n=3):
    return {
        **entry(i, n=n),
        "authors": {
            "privateNames": 1,
            "publicNames": 1,
            "publicAuthors": [{"name": "Teemu Teekkari", "municipality": MUNIS[0]}],
        },
        "participantCount": {"externalNames": 0, "privateNames": n - 1, "publicNames": 1, "total": n},
        "proposal": f"Ehdotamme puistoa {i}. Lisätietoja teemu@example.org, puh. 040 123 4567.",
    }


class Api:
    def __init__(self, helsinki=60, espoo=2):
        self.lists = {
            91: [entry(i) for i in range(1, helsinki + 1)],
            49: [entry(1000 + i, 49) for i in range(espoo)],
        }
        self.paths: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.paths.append(req.url.path + ("?" + req.url.query.decode() if req.url.query else ""))
        p = req.url.path
        if p == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if p == "/api/v1/municipalities":
            return httpx.Response(200, json=MUNIS)
        if p == "/api/v1/initiatives":
            q = req.url.params
            rows = self.lists[int(q["municipality"])]
            off, lim = int(q["offset"]), int(q["limit"])
            return httpx.Response(200, json=rows[off : off + lim])
        if p.startswith("/api/v1/initiatives/"):
            i = int(p.rsplit("/", 1)[1])
            return httpx.Response(200, json=detail(i))
        return httpx.Response(404)


def client(handler, exceptions=EXC):
    return PoliteClient(
        UA,
        transport=httpx.MockTransport(handler),
        rate_limiter=RateLimiter(sleep=lambda s: None, clock=lambda: 0.0),
        sleep=lambda s: None,
        allowed_hosts={HOST},
        robots_exceptions=exceptions,
    )


def test_robots_exception_covers_only_the_listed_paths():
    api = Api()
    c = client(api)
    assert c.get(f"{API}/municipalities").status == 200
    with pytest.raises(RobotsDisallowed):
        c.get(f"https://{HOST}/fi/hae")
    with pytest.raises(RobotsDisallowed):
        client(api, exceptions={}).get(f"{API}/municipalities")


def test_run_pages_lists_strips_authors_and_pii(tmp_path):
    api = Api()
    stats = run(client(api), {"helsinki": "Helsinki", "espoo": "Espoo", "oulu": "Oulu"}, tmp_path)
    assert stats.unmatched == ["Oulu"]
    assert stats.initiatives == 62 and stats.details_fetched == 62
    hel = jsonio.read(tmp_path / "helsinki.json")
    assert hel["source_municipality_id"] == 91 and hel["active_in_service"] is True
    ids = [r["id"] for r in hel["initiatives"]]
    assert ids == sorted(ids, reverse=True) and len(ids) == 60
    # 60 initiatives at 50 per page: offsets 0 and 50
    assert [p for p in api.paths if "municipality=91" in p] == [
        "/api/v1/initiatives?municipality=91&limit=50&offset=0&orderBy=id",
        "/api/v1/initiatives?municipality=91&limit=50&offset=50&orderBy=id",
    ]
    rec = hel["initiatives"][-1]
    assert rec["authors"] == 2 and rec["participants"] == 3
    assert rec["url_fi"].endswith("/fi/aloite/1")
    raw = (tmp_path / "helsinki.json").read_text()
    assert "Teemu" not in raw and "teemu@example.org" not in raw and "040 123" not in raw
    assert "[poistettu]" in rec["proposal"]


def test_rerun_fetches_only_new_initiatives_and_is_byte_identical(tmp_path):
    cities = {"helsinki": "Helsinki"}
    run(client(Api()), cities, tmp_path)
    before = (tmp_path / "helsinki.json").read_bytes()
    api = Api()
    api.lists[91][0] = entry(1, sent="2026-03-01", n=5)  # sent, and the list's count differs
    api.lists[91].append(entry(61))  # a new initiative
    stats = run(client(api), cities, tmp_path)
    assert stats.details_fetched == 1 and stats.details_reused == 60
    assert [p for p in api.paths if p.startswith("/api/v1/initiatives/")] == ["/api/v1/initiatives/61"]
    after = jsonio.read(tmp_path / "helsinki.json")
    first = next(r for r in after["initiatives"] if r["id"] == 1)
    assert first["sent_date"] == "2026-03-01"  # list fields are refreshed
    assert first["participants"] == 3 and "proposal" in first  # details are kept
    assert any(r["id"] == 61 and "proposal" in r for r in after["initiatives"])
    run(client(api), cities, tmp_path)
    again = (tmp_path / "helsinki.json").read_bytes()
    assert again != before and json.loads(again) == after


def test_bot_check_page_is_reported(tmp_path):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        return httpx.Response(403, text="<title>Just a moment...</title>")

    with pytest.raises(BotCheck):
        run(client(handler), {"helsinki": "Helsinki"}, tmp_path)


def test_helpers():
    assert api_id(f"{API}/initiatives/123") == 123
    assert api_id(None) is None
    mapping, missing = match_municipalities(MUNIS, {"helsinki": "Helsinki", "x": "Nowhere"})
    assert mapping == {"helsinki": 91} and missing == ["Nowhere"]
