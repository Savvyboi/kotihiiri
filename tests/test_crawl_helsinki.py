import datetime as dt

from kunta import jsonio
from kunta.adapters.helsinki import HelsinkiAdapter
from kunta.crawl import crawl
from kunta.validate import validate_city
from tests.helsinki_site import FakeHelsinki, client

TODAY = dt.date(2026, 10, 11)


def run(tmp_path, site=None, **kw):
    site = site or FakeHelsinki()
    (tmp_path / "config" / "bodies").mkdir(parents=True, exist_ok=True)
    report = crawl(
        HelsinkiAdapter(client(site)),
        "helsinki",
        since=dt.date(2025, 1, 1),
        today=TODAY,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        **kw,
    )
    return report, site


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_full_crawl_writes_meetings_and_validates(tmp_path):
    report, _ = run(tmp_path)
    assert report.alarms == [] and report.parse_errors == 0
    data = tmp_path / "data"
    files = sorted(p.name for p in (data / "helsinki" / "meetings").rglob("*.json"))
    assert files == [
        "kaupunginvaltuusto--2025-01-15.json",
        "kaupunginvaltuusto--2026-09-09.json",
        "kaupunginvaltuusto--2026-09-23.json",
        "kaupunginvaltuusto--2026-10-07.json",
    ]
    mf = jsonio.read(data / "helsinki" / "meetings" / "2026" / "kaupunginvaltuusto--2026-09-23.json")
    assert mf["meeting"]["stage"] == "minutes"
    assert [i["ordinal"] for i in mf["items"]] == [1, 2, 13]
    assert mf["items"][2]["votes"][0]["counts"] == {"jaa": 34, "ei": 36, "tyhja": 15, "poissa": 0}
    bodies = jsonio.read(data / "helsinki" / "bodies.json")
    assert any(b["id"] == "helsinki/kaupunginvaltuusto" for b in bodies)
    yaml_text = (tmp_path / "config" / "bodies" / "helsinki.yaml").read_text(encoding="utf-8")
    assert "keskusvaalilautakunta:" in yaml_text and "excluded_by_rule: true" in yaml_text
    r = validate_city("helsinki", data)
    assert r.ok, r.errors


def test_second_run_produces_no_diff(tmp_path):
    run(tmp_path)
    before = snapshot(tmp_path)
    report, _ = run(tmp_path)
    assert report.files_changed == 0
    assert snapshot(tmp_path) == before


def test_window_skips_old_minutes_meetings(tmp_path):
    run(tmp_path)
    report, site = run(tmp_path, window_weeks=10)
    # only 2025-01-15 is a minutes-stage meeting older than 10 weeks
    assert report.meetings_skipped == 1
    assert not any(u.endswith("/0290020251") for u in site.requests)
    # the agenda-stage meeting is refetched to catch the minutes
    assert any(u.endswith("/02900202615") for u in site.requests)


def test_manual_body_flag_survives_rediscovery(tmp_path):
    run(tmp_path)
    path = tmp_path / "config" / "bodies" / "helsinki.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "  tarkastuslautakunta:\n", "  tarkastuslautakunta:\n    included: false\n"
        ),
        encoding="utf-8",
    )
    run(tmp_path)
    assert "included: false" in path.read_text(encoding="utf-8")


def test_load_error_retried_then_marked_needs_refetch(tmp_path):
    site = FakeHelsinki()
    site.overrides["/fi/asia/26ac134e-452f-43dd-a7e2-42600821c38e"] = "item-load-error.html"
    report, _ = run(tmp_path, site=site)
    calls = [u for u in site.requests if u.startswith("/fi/asia/26ac134e")]
    assert len(calls) == 2 * 3  # three meetings reuse this page; each item tried twice
    state = jsonio.read(tmp_path / "data" / "state" / "helsinki.json")
    assert "helsinki/kaupunginvaltuusto/2026-09-23/1" in state["needs_refetch"]
    # next run with the page fixed clears it, even for a meeting outside the window
    report, _ = run(tmp_path, window_weeks=1)
    assert jsonio.read(tmp_path / "data" / "state" / "helsinki.json")["needs_refetch"] == []


def test_item_removed_at_source_becomes_tombstone_after_two_misses(tmp_path):
    run(tmp_path)
    site = FakeHelsinki()
    site.status["/fi/asia/a2811877-54a9-cb9a-b604-a11a3c700002"] = 404
    run(tmp_path, site=site)
    path = tmp_path / "data" / "helsinki" / "meetings" / "2026" / "kaupunginvaltuusto--2026-09-23.json"
    assert jsonio.read(path)["items"][1]["status"] == "active"
    run(tmp_path, site=site)
    item = jsonio.read(path)["items"][1]
    assert item["status"] == "tombstone" and item["sections"] == []


def test_layout_alarm_when_body_lists_nothing(tmp_path):
    run(tmp_path)
    site = FakeHelsinki()
    site.overrides["/fi/paattajat/kaupunginvaltuusto/asiakirjat"] = "lautakunnat-ja-johtokunnat.html"
    report, _ = run(tmp_path, site=site)
    assert report.alarms == ["no meetings found for active body helsinki/kaupunginvaltuusto"]
