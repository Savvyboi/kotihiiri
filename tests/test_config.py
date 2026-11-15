import pytest

from kunta.adapters import NotEnabled, adapter_for
from kunta.config import ConfigError, ProjectConfig, load_cities
from kunta.http import PoliteClient


def test_oulu_and_turku_enabled():
    cities = load_cities()
    assert list(cities)[:6] == ["helsinki", "espoo", "tampere", "vantaa", "oulu", "turku"]
    assert len(cities) == 96
    assert cities["oulu"].enabled is True
    assert cities["oulu"].adapter == "tweb"
    assert cities["turku"].enabled is True
    assert cities["turku"].adapter == "turku"


def test_disabled_city_adapter_refuses():
    with pytest.raises(NotEnabled):
        adapter_for("vaasa", PoliteClient("ua"))


def test_user_agent_requires_domain_and_email():
    p = ProjectConfig(
        "K", None, None, "KuntaDataBot/0.1 (+https://{site_domain}/tietoa; {contact_email})", "2025-01-01", {}
    )
    with pytest.raises(ConfigError):
        _ = p.user_agent
    p2 = ProjectConfig("K", "kotihiiri.fi", "a@b.fi", p.user_agent_template, "2025-01-01", {})
    assert p2.user_agent == "KuntaDataBot/0.1 (+https://kotihiiri.fi/tietoa; a@b.fi)"


def test_speeches_by_person_flag():
    from kunta.config import load_project

    # On since the legal check in PLAN.md §2.2 rule 9 (2026-10-14); the site reads the same flag.
    assert load_project().features["SPEECHES_BY_PERSON"] is True


def test_local_crawl_cities_stay_out_of_the_actions_matrix():
    from kunta.registry import crawl_groups

    assert load_cities()["turku"].extra.get("crawl_from") == "local"
    assert not any("turku" in g["cities"].split(",") for g in crawl_groups())
    assert crawl_groups(["turku"]) == [{"name": "turku", "cities": "turku", "storage": "git"}]
