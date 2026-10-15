"""Registry, provider caps, body scope and the robots audit (PLAN.md §18, M10)."""

import httpx

from kunta import registry
from kunta.audit import check_host
from kunta.bodies import default_included, guess_kind
from kunta.config import load_cities
from kunta.http import PoliteClient, RateLimiter
from kunta.models import BodyKind
from tests.test_http import UA, FakeClock


def test_committed_registry_is_up_to_date():
    assert not registry.is_stale(), "run `kunta registry`"


def test_registry_rows():
    cities = load_cities()
    assert len(cities) == 96
    assert list(cities)[6:8] == ["jyvaskyla", "kuopio"]
    assert list(cities)[-1] == "sotkamo"
    kuopio = cities["kuopio"]
    assert kuopio.adapter == "dynasty"
    assert kuopio.base_urls == ["https://kuopio.oncloudos.com"]
    assert kuopio.extra["council_source_id"] == "1"
    assert kuopio.extra["provider"] == "oncloudos.com"
    assert kuopio.extra["bodies_scope"] == "council_board"
    # Self-hosted Dynasty keeps its path prefix; Swedish-language municipalities get Finnish slugs.
    assert cities["joensuu"].base_urls == ["https://dynastyjulkaisu.pohjoiskarjala.net/joensuu"]
    assert cities["raasepori"].name_sv == "Raseborg"
    assert cities["raasepori"].extra["lang"] == "sv"
    assert cities["jyvaskyla"].extra["council_source_id"] == "Kaupunginvaltuusto"
    assert cities["pietarsaari"].base_urls == ["https://mote.jakobstad.fi:8443"]
    assert cities["pietarsaari"].extra["tweb_dll_paths"] is True


def test_every_registry_row_has_adapter_or_reason():
    for slug, c in load_cities().items():
        assert c.adapter, slug
        if c.adapter == "none":
            assert not c.enabled and c.reason == "no_adapter", slug
        if not c.enabled:
            assert c.reason, slug
    none = sorted(s for s, c in load_cities().items() if c.adapter == "none")
    assert none == ["alavus", "hyvinkaa", "imatra", "kotka", "kurikka", "lappeenranta", "mustasaari"]


def test_gate():
    entry = {"adapter": "dynasty", "base_urls": ["https://x.oncloudos.com"]}
    assert registry._gate(entry, {}, set(), "x") == (False, "robots_audit_pending")
    robots = {"x.oncloudos.com": {"status": "partial"}}
    assert registry._gate(entry, robots, {"x"}, "x") == (False, "robots_disallow_pending_permission")
    robots = {"x.oncloudos.com": {"status": "allowed"}}
    assert registry._gate(entry, robots, set(), "x") == (False, "rollout_pending")
    assert registry._gate(entry, robots, {"x"}, "x") == (True, None)


def test_provider_of():
    assert registry.provider_of("lahti-prod.oncloudos.com") == "oncloudos.com"
    assert registry.provider_of("mote.jakobstad.fi:8443") == "mote.jakobstad.fi"
    assert registry.provider_of("hameenlinna.tweb.fi") == "tweb.fi"


def test_provider_cap_spans_hosts():
    clock = FakeClock()
    rl = RateLimiter(clock=clock.clock, sleep=clock.sleep)
    rl.wait("a.oncloudos.com")
    rl.wait("b.oncloudos.com")  # other host, same provider: 0.5 s
    rl.wait("c.example")  # unrelated host: no wait
    rl.wait("a.oncloudos.com")  # 1 s since its last request has not passed: 0.5 s more
    assert clock.sleeps == [0.5, 0.5]


def test_body_scope_and_kinds():
    assert guess_kind("Kunnanhallitus") == BodyKind.board
    assert guess_kind("Hallitus") == BodyKind.board
    assert guess_kind("Stadsstyrelsen") == BodyKind.board
    assert guess_kind("Stadsfullmäktige") == BodyKind.council
    assert guess_kind("Kaupunginhallituksen elinvoimajaosto") == BodyKind.section
    assert guess_kind("Kunnanhallitus - Kommunstyrelsen") == BodyKind.board
    assert guess_kind("Kunnanhallitus ⁄ Kommunstyrelsen") == BodyKind.board
    assert guess_kind("Elinvoima- ja työllisyysjaosto") == BodyKind.section
    assert guess_kind("Kaupunginhallitus, strategiset yhtiöt") == BodyKind.committee
    assert not default_included("Kaupunginhallitus, salassa pidettävät asiat", "pori")
    assert not default_included("Lapsivaltuusto - Barnfullmäktige", "kokkola")
    assert not default_included("Stadsstyrelsen", "porvoo")
    # Registry municipalities: council and board only (§17).
    assert default_included("Kaupunginvaltuusto", "kuopio")
    assert default_included("Kaupunginhallitus", "kuopio")
    assert not default_included("Tekninen lautakunta", "kuopio")
    assert not default_included("Kaupunginhallituksen konsernijaosto", "kuopio")
    assert not default_included("Nuorisovaltuusto", "kuopio")
    # The six keep every decision-making body; Vantaa's Swedish council is a duplicate.
    assert default_included("Tekninen lautakunta", "espoo")
    assert not default_included("Stadsfullmäktige", "vantaa")
    # In a Swedish-language municipality the Swedish council is the council.
    assert default_included("Stadsfullmäktige", "raasepori")
    assert not default_included("Ungdomsfullmäktige", "raasepori")


def _client(robots_text, status=200):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(status, text=robots_text)
        return httpx.Response(200, text="ok")

    clock = FakeClock()
    return PoliteClient(
        UA,
        transport=httpx.MockTransport(handler),
        rate_limiter=RateLimiter(clock=clock.clock, sleep=clock.sleep),
        sleep=clock.sleep,
    )


def test_audit_host_statuses():
    kuopio = load_cities()["kuopio"]
    base = kuopio.base_urls[0]
    assert check_host(_client("User-agent: *\nDisallow: /admin/\n"), kuopio, base).status == "allowed"
    assert check_host(_client("User-agent: *\nDisallow: /\n"), kuopio, base).status == "disallowed"
    res = check_host(_client("User-agent: *\nDisallow: /kokous/\n"), kuopio, base)
    assert res.status == "partial"
    assert res.blocked == ["/kokous/20251-1-1.PDF", "/kokous/20251.PDF"]
    assert check_host(_client("", 404), kuopio, base).status == "no_robots"
    assert check_host(_client("", 403), kuopio, base).status == "disallowed"
    assert check_host(_client("", 503), kuopio, base).status == "unreachable"
