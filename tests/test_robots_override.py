"""Robots override (PLAN.md §2.1 rule 1b): off by default, gentle, and never past a refusal."""

import httpx
import pytest

from kunta import registry
from kunta.config import ConfigError, RobotsOverride, _robots_override, load_cities, load_project
from kunta.http import HostRefused, PoliteClient, RateLimiter, RobotsDisallowed
from kunta.robots import RobotsRules
from tests.test_http import UA, FakeClock

DISALLOW_ALL = "User-agent: *\nDisallow: /\n"


def make(handler, hosts=("blocked.example",), interval=5.0):
    clock = FakeClock()
    client = PoliteClient(
        UA,
        transport=httpx.MockTransport(handler),
        rate_limiter=RateLimiter(clock=clock.clock, sleep=clock.sleep, provider_of=lambda h: h),
        sleep=clock.sleep,
        robots_override_hosts=set(hosts),
        robots_override_interval_s=interval,
    )
    return client, clock


def test_override_is_off_in_the_committed_config():
    ro = load_project().robots_override
    assert ro.enabled is False
    assert ro.approved_by and ro.approved_on
    assert ro.min_interval_s >= 5
    # The 26 municipalities the audit found disallowed or partial; none of the six cities.
    assert len(ro.municipalities) == 26
    assert not {"oulu", "turku"} & set(ro.municipalities)
    cities = load_cities()
    for slug in ro.municipalities:
        assert cities[slug].enabled is False, slug
        assert cities[slug].reason == "robots_disallow_pending_permission", slug


def test_off_means_robots_still_blocks():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=DISALLOW_ALL)
        raise AssertionError("must not fetch")

    client, _ = make(handler, hosts=())
    with pytest.raises(RobotsDisallowed):
        client.get("https://blocked.example/minutes")


def test_override_fetches_disallowed_url_slowly_with_our_user_agent():
    seen = []

    def handler(req):
        seen.append((req.url.path, req.headers["user-agent"]))
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=DISALLOW_ALL)
        return httpx.Response(200, text="ok")

    client, clock = make(handler)
    for i in range(3):
        assert client.get(f"https://blocked.example/{i}").status == 200
    assert [p for p, _ in seen] == ["/robots.txt", "/0", "/1", "/2"]
    assert {ua for _, ua in seen} == {UA}
    assert clock.sleeps == [5.0, 5.0, 5.0]
    assert client.stats.robots_overridden == 3
    # Other hosts are untouched by the override.
    with pytest.raises(RobotsDisallowed):
        client.get("https://other.example/x")


def test_longer_crawl_delay_wins():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 20\nDisallow: /\n")
        return httpx.Response(200, text="ok")

    client, clock = make(handler)
    client.get("https://blocked.example/a")
    client.get("https://blocked.example/b")
    assert clock.sleeps == [20.0, 20.0]


@pytest.mark.parametrize("robots", [403, 401, 503])
def test_override_never_passes_a_refused_or_failing_robots_txt(robots):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(robots)
        raise AssertionError("must not fetch")

    client, _ = make(handler)
    with pytest.raises(RobotsDisallowed):
        client.get("https://blocked.example/minutes")


def test_unreachable_robots_still_blocks_under_override():
    def handler(req):
        if req.url.path == "/robots.txt":
            raise httpx.ConnectError("down")
        raise AssertionError("must not fetch")

    client, _ = make(handler)
    with pytest.raises(RobotsDisallowed):
        client.get("https://blocked.example/minutes")


def test_403_stops_the_host_for_the_run():
    fetched = []

    def handler(req):
        fetched.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=DISALLOW_ALL)
        return httpx.Response(403)

    client, _ = make(handler)
    assert client.get("https://blocked.example/a").status == 403
    with pytest.raises(HostRefused):
        client.get("https://blocked.example/b")
    assert fetched == ["/robots.txt", "/a"]


def test_429_after_retries_stops_the_host():
    fetched = []

    def handler(req):
        fetched.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=DISALLOW_ALL)
        return httpx.Response(429, headers={"Retry-After": "60"})

    client, clock = make(handler)
    with pytest.raises(HostRefused):
        client.get("https://blocked.example/a")
    with pytest.raises(HostRefused):
        client.get("https://blocked.example/b")
    assert fetched == ["/robots.txt"] + ["/a"] * 4
    assert 60.0 in clock.sleeps


def test_crawl_delay_parsing():
    rules = RobotsRules(
        "User-agent: *\nCrawl-delay: 3\n\nUser-agent: KuntaDataBot\nCrawl-delay: x\nDisallow: /a\n"
    )
    assert rules.crawl_delay(UA) is None  # our group has no valid delay; the * group does not apply
    assert RobotsRules("User-agent: *\nCrawl-delay: 2.5\n").crawl_delay(UA) == 2.5


def test_config_validation():
    assert _robots_override({}) == RobotsOverride()
    assert _robots_override({"enabled": False, "municipalities": ["lohja"]}).applies_to("lohja") is False
    on = _robots_override(
        {"enabled": True, "approved_by": "X", "approved_on": "2026-11-10", "municipalities": ["lohja"]}
    )
    assert on.applies_to("lohja") and not on.applies_to("kerava")
    with pytest.raises(ConfigError):
        _robots_override({"enabled": True, "municipalities": ["lohja"]})  # no approval recorded
    with pytest.raises(ConfigError):
        _robots_override({"enabled": "yes"})
    with pytest.raises(ConfigError):
        _robots_override({"min_interval_s": 0.5})
    with pytest.raises(ConfigError):
        _robots_override({"municipalities": ["lohja", "lohja"]})


def test_gate_with_override():
    entry = {"adapter": "tweb", "base_urls": ["https://x.tweb.fi"]}
    on = frozenset({"x"})
    for status in ("disallowed", "partial"):
        robots = {"x.tweb.fi": {"status": status}}
        assert registry._gate(entry, robots, {"x"}, "x") == (False, "robots_disallow_pending_permission")
        assert registry._gate(entry, robots, {"x"}, "x", on) == (True, None)
        assert registry._gate(entry, robots, set(), "x", on) == (False, "rollout_pending")
    # Unreachable hosts are not covered.
    robots = {"x.tweb.fi": {"status": "unreachable"}}
    assert registry._gate(entry, robots, {"x"}, "x", on) == (False, "host_unreachable")
