import pytest

from kunta.adapters import NotEnabled, adapter_for
from kunta.config import ConfigError, ProjectConfig, load_cities
from kunta.http import PoliteClient


def test_oulu_and_turku_disabled_with_reason():
    cities = load_cities()
    assert list(cities) == ["helsinki", "espoo", "tampere", "vantaa", "oulu", "turku"]
    for c in ("oulu", "turku"):
        assert cities[c].enabled is False
        assert cities[c].reason == "robots_disallow_pending_permission"
    assert cities["oulu"].adapter == "tweb"


def test_disabled_city_adapter_refuses():
    client = PoliteClient("ua")
    for c in ("oulu", "turku"):
        with pytest.raises(NotEnabled):
            adapter_for(c, client)


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
