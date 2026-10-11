from kunta.robots import RobotsRules
from tests.helsinki_site import ROBOTS

UA = "KuntaDataBot/0.1 (+https://example.org/tietoa; test@example.org)"


def test_wildcard_query_rules_match():
    r = RobotsRules(ROBOTS)
    base = "https://paatokset.hel.fi"
    assert not r.can_fetch(UA, f"{base}/fi/paattajat/kaupunginvaltuusto/asiakirjat?from=2025-01-01")
    assert not r.can_fetch(UA, f"{base}/fi/asia?s=raitiotie")
    assert not r.can_fetch(UA, f"{base}/fi/asia?page=2&dm=123")
    assert not r.can_fetch(UA, f"{base}/search?q=x")
    assert not r.can_fetch(UA, f"{base}/core/misc/x.js")


def test_urls_the_helsinki_adapter_uses_are_allowed():
    r = RobotsRules(ROBOTS)
    base = "https://paatokset.hel.fi"
    for path in (
        "/fi/paattajat/lautakunnat-ja-johtokunnat",
        "/fi/paattajat/kaupunginvaltuusto/asiakirjat?page=3",
        "/fi/paattajat/kaupunginvaltuusto/asiakirjat/02900202614",
        "/fi/asia/hel-2026-008342?paatos=6c1e0a7d-0000-4000-8000-000000000001",  # "paatos=" is not "to="
    ):
        assert r.can_fetch(UA, base + path), path


def test_longest_match_and_allow_wins_tie():
    r = RobotsRules("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /x$\nAllow: /p\nDisallow: /p\n")
    assert not r.can_fetch(UA, "https://h/a/c")
    assert r.can_fetch(UA, "https://h/a/b/c")
    assert not r.can_fetch(UA, "https://h/x")
    assert r.can_fetch(UA, "https://h/xy")
    assert r.can_fetch(UA, "https://h/p")


def test_named_group_replaces_star_group():
    r = RobotsRules("User-agent: *\nDisallow: /\n\nUser-agent: KuntaDataBot\nDisallow: /private\n")
    assert r.can_fetch(UA, "https://h/public")
    assert not r.can_fetch(UA, "https://h/private/x")
    assert not r.can_fetch("OtherBot/1.0", "https://h/public")


def test_consecutive_user_agent_lines_share_a_group():
    r = RobotsRules("User-agent: foo\nUser-agent: kuntadatabot\nDisallow: /x\n")
    assert not r.can_fetch(UA, "https://h/x")
