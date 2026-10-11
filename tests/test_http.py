import httpx
import pytest

from kunta.http import FetchFailed, PoliteClient, RateLimiter, RobotsDisallowed

UA = "KuntaDataBot/0.1 (+https://example.org/tietoa; test@example.org)"
ROBOTS = "User-agent: *\nDisallow: /private/\n"
ROBOTS_NAMED = "User-agent: *\nDisallow: /\n\nUser-agent: KuntaDataBot\nDisallow: /nobots/\n"


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def make_client(handler, tmp_path=None, clock=None):
    clock = clock or FakeClock()
    return PoliteClient(
        UA,
        transport=httpx.MockTransport(handler),
        rate_limiter=RateLimiter(clock=clock.clock, sleep=clock.sleep),
        sleep=clock.sleep,
        cache_dir=tmp_path / "raw" if tmp_path else None,
    ), clock


def test_robots_disallowed_url_is_never_fetched():
    fetched = []

    def handler(req):
        fetched.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        return httpx.Response(200, text="ok")

    client, _ = make_client(handler)
    with pytest.raises(RobotsDisallowed):
        client.get("https://city.example/private/minutes")
    assert client.get("https://city.example/public").status == 200
    assert fetched == ["/robots.txt", "/public"]
    assert client.stats.skipped_robots == ["https://city.example/private/minutes"]


def test_robots_group_for_our_user_agent_applies():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_NAMED)
        return httpx.Response(200, text="ok")

    client, _ = make_client(handler)
    with pytest.raises(RobotsDisallowed):
        client.get("https://city.example/nobots/x")
    assert client.get("https://city.example/public").status == 200


def test_robots_disallow_all_blocks_host():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        raise AssertionError("must not fetch")

    client, _ = make_client(handler)
    with pytest.raises(RobotsDisallowed):
        client.get("https://paatokset.turku.fi/kaupunginvaltuusto")


def test_unreachable_robots_blocks_host():
    def handler(req):
        if req.url.path == "/robots.txt":
            raise httpx.ConnectError("down")
        raise AssertionError("must not fetch")

    client, _ = make_client(handler)
    with pytest.raises(RobotsDisallowed):
        client.get("https://down.example/x")


def test_user_agent_sent():
    seen = []

    def handler(req):
        seen.append(req.headers["user-agent"])
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200)

    client, _ = make_client(handler)
    client.get("https://a.example/")
    assert seen == [UA, UA]


def test_rate_limit_one_request_per_second_per_host():
    def handler(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200)

    client, clock = make_client(handler)
    for i in range(3):
        client.get(f"https://a.example/{i}")
    # robots + 3 pages on the same host: three waits of 1 s each (clock does not advance otherwise)
    assert clock.sleeps == [1.0, 1.0, 1.0]
    client.get("https://b.example/0")  # other host: only its own robots+page spacing
    assert clock.sleeps[3:] == [1.0]


def test_rate_limiter_no_wait_when_interval_passed():
    clock = FakeClock()
    rl = RateLimiter(clock=clock.clock, sleep=clock.sleep)
    rl.wait("h")
    clock.now += 5
    rl.wait("h")
    assert clock.sleeps == []


def test_retry_after_and_give_up():
    calls = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        return httpx.Response(503, headers={"Retry-After": "7"})

    client, clock = make_client(handler)
    with pytest.raises(FetchFailed):
        client.get("https://a.example/x")
    assert len(calls) == 4
    assert [s for s in clock.sleeps if s != 1.0] == [7.0, 7.0, 7.0]
    assert client.stats.failures[0]["error"] == "HTTP 503"


def test_exponential_backoff_then_success():
    n = {"i": 0}

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        n["i"] += 1
        return httpx.Response(429) if n["i"] < 3 else httpx.Response(200, text="ok")

    client, clock = make_client(handler)
    assert client.get("https://a.example/x").text == "ok"
    assert [s for s in clock.sleeps if s != 1.0] == [2.0, 4.0]


def test_conditional_get_uses_cache(tmp_path):
    seen = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        seen.append(dict(req.headers))
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, text="body", headers={"ETag": '"v1"', "Content-Type": "text/html"})

    client, _ = make_client(handler, tmp_path)
    first = client.get("https://a.example/doc")
    second = client.get("https://a.example/doc")
    assert first.text == second.text == "body"
    assert second.from_cache and client.stats.not_modified == 1
    assert "if-none-match" not in seen[0]


def test_disallowed_host_rejected():
    client = PoliteClient(
        UA, transport=httpx.MockTransport(lambda r: httpx.Response(200)), allowed_hosts={"a.example"}
    )
    with pytest.raises(FetchFailed):
        client.get("https://asiakirjat.ouka.fi/x")


def test_charset_decoding():
    from kunta.http import Response

    r = Response("u", 200, "Päätös".encode("iso-8859-1"), {"content-type": "text/html; charset=ISO-8859-1"})
    assert r.text == "Päätös"
