import datetime as dt
from pathlib import Path

import pytest

from kunta import jsonio
from kunta.adapters.base import TransientItemError
from kunta.adapters.dynasty import DynastyAdapter
from kunta.crawl import crawl
from kunta.models import Body, ItemRef, MeetingRef, Stage
from kunta.parsers import dynasty as dp
from kunta.parsers import votes_cloudmeeting as vc
from kunta.text import contains_pii
from kunta.validate import validate_city
from tests.espoo_site import FIXTURES, FakeEspoo, client

GOLDEN = Path(__file__).resolve().parent / "golden" / "espoo"
CGI = "https://espoo.oncloudos.com/cgi/DREQUEST.PHP"
COUNCIL = Body(id="espoo/valtuusto", city="espoo", name_fi="Valtuusto", kind="council",
               source_ids={"dynasty_id": "1"})  # fmt: skip
TODAY = dt.date(2026, 10, 13)

# PLAN.md §7.2: body ids on 2026-10-11, used as test expectations.
EXPECTED_IDS = {
    "Valtuusto": "1", "Kaupunginhallitus": "182", "Kaupunkisuunnittelulautakunta": "162",
    "Tekninen lautakunta": "160", "Kasvun ja oppimisen lautakunta": "46162",
    "Kasvun ja oppimisen lautakunnan nuorisoasiainjaosto": "46164",
    "Kaupunginhallituksen elinkeino- ja kilpailukykyjaosto": "2243",
    "Kaupunginhallituksen konserni- ja tilajaosto": "164724", "Kaupunginhallituksen konsernijaosto": "616",
    "Kaupunginhallituksen tila- ja asuntojaosto": "617",
    "Kaupunginhallituksen työllisyys- ja kotoutumisjaosto": "165188",
    "Kaupunginhallituksen työllisyysjaosto": "152830", "Kulttuuri- ja nuorisolautakunta": "164718",
    "Kulttuurilautakunta": "161", "Liikunta- ja hyvinvointilautakunta": "164720", "Liikuntalautakunta": "46112",
    "Nämnden Svenska rum": "890", "Tarkastuslautakunta": "2029", "Ympäristö- ja rakennuslautakunta": "46088",
}  # fmt: skip


def adapter(site=None):
    return DynastyAdapter(client(site or FakeEspoo()))


def item_ref(mid: str, n: int, meeting="espoo/valtuusto/2026-09-21", pykala=132, stage=Stage.minutes):
    return ItemRef(meeting_id=meeting, ordinal=n, source_url=f"{CGI}?page=meetingitem&id={mid}-{n}",
                   stage=stage, pykala=pykala, title="Otsikko")  # fmt: skip


def olari(site=None):
    return adapter(site).fetch_item(item_ref("20261715", 13))


# -- pages ----------------------------------------------------------------------------------


def test_decode_handles_latin1_listing_and_utf8_items():
    raw = (FIXTURES / "meeting_frames.html").read_bytes()
    assert b"\xe4" in raw  # ä in ISO-8859-1
    assert "Nämnden Svenska rum" in dp.decode(raw)
    assert "Nämnden" in dp.decode("Nämnden".encode(), "iso-8859-1")  # wrong header, valid UTF-8


def test_discover_bodies_match_plan_ids_and_exclude_rules():
    bodies = {b.name_fi: b for b in adapter().discover_bodies()}
    assert {n: b.source_ids["dynasty_id"] for n, b in bodies.items() if n in EXPECTED_IDS} == EXPECTED_IDS
    assert "Testitoimielin" not in bodies  # no published meetings, no link
    assert not bodies["Keskusvaalilautakunta"].included
    assert bodies["Valtuusto"].id == "espoo/valtuusto" and bodies["Valtuusto"].kind == "council"
    assert bodies["Kaupunginhallitus"].kind == "board"
    assert bodies["Kaupunginhallituksen konsernijaosto"].kind == "section"
    assert bodies["Nämnden Svenska rum"].id == "espoo/namnden-svenska-rum"


def test_list_meetings_since_2025_with_stage_from_listing():
    refs = adapter().list_meetings(COUNCIL, dt.date(2025, 1, 1), None)
    assert [(r.date.isoformat(), r.stage, r.source_ids["meeting_id"]) for r in refs] == [
        ("2025-12-08", "minutes", "20251553"),
        ("2026-09-21", "minutes", "20261715"),
        ("2026-10-19", "agenda", "20261743"),
    ]


def test_fetch_minutes_meeting():
    a = adapter()
    ref = MeetingRef(body_id="espoo/valtuusto", date=dt.date(2026, 9, 21), stage=Stage.minutes,
                     source_url=f"{CGI}?page=meeting&id=20261715", source_ids={"meeting_id": "20261715"})  # fmt: skip
    m = a.fetch_meeting(ref)
    assert m.id == "espoo/valtuusto/2026-09-21"
    assert (m.start_time, m.end_time, m.location) == ("17:30", "19:53", "Valtuustotalo, Espoonkatu 5")
    assert m.minutes_pdf_url == "https://espoo.oncloudos.com/kokous/20261715.PDF"
    assert m.items == [
        "espoo/valtuusto/2026-09-21/1",
        "espoo/valtuusto/2026-09-21/2",
        "espoo/valtuusto/2026-09-21/13",
    ]
    assert len(m.attendance) == 77
    assert (m.attendance[0].person_ref.raw, m.attendance[0].role_text) == (
        "Esimerkki Ilmari",
        "puheenjohtaja",
    )
    refs = a.item_refs(m)
    assert [(r.ordinal, r.pykala) for r in refs] == [(1, 120), (2, 121), (13, 132)]


def test_agenda_meeting_has_no_attendance_or_pykala():
    a = adapter()
    ref = MeetingRef(body_id="espoo/valtuusto", date=dt.date(2026, 10, 19), stage=Stage.agenda,
                     source_url=f"{CGI}?page=meeting&id=20261743", source_ids={"meeting_id": "20261743"})  # fmt: skip
    m = a.fetch_meeting(ref)
    assert m.stage == "agenda" and m.attendance == [] and m.minutes_pdf_url is None
    assert (m.start_time, m.end_time, m.location) == ("17:30", None, "Valtuustotalo, Espoonkatu 5")
    assert all(r.pykala is None for r in a.item_refs(m))


def test_page_heading_saying_minutes_wins_over_a_lagging_listing():
    ref = MeetingRef(body_id="espoo/valtuusto", date=dt.date(2026, 9, 21), stage=Stage.agenda,
                     source_url=f"{CGI}?page=meeting&id=20261715", source_ids={"meeting_id": "20261715"})  # fmt: skip
    assert adapter().fetch_meeting(ref).stage == "minutes"


# -- items ----------------------------------------------------------------------------------


def test_item_sections_header_and_attachments():
    item = olari()
    kinds = [s.type for s in item.sections]
    assert kinds == ["proposal", "deliberation", "decision", "background", "history", "history"]
    assert item.case_number == "1312/10.03.02/2025"
    assert item.presenter == "Kaupunginhallitus"
    assert item.preparers == ["Valmistelija Vilma"]
    assert item.pykala == 132
    decision = next(s for s in item.sections if s.type == "decision")
    assert "hyväksyttiin yksimielisesti" in decision.text
    assert [s.heading for s in item.sections if s.type == "history"] == [
        "Kaupunginhallituksen konserni- ja tilajaosto 23.03.2026 § 30",
        "Kaupunginhallitus 17.08.2026 § 266",
    ]
    assert [(a.title, a.kind) for a in item.attachments] == [
        ("Liite 1 Olarin uimahallin valokuvakooste 8.6.2026", "attachment"),
        ("Liite 2 Äänestyslista § 132", "attachment"),
        ("Oheismateriaali 1 Valtuustoaloite Olarin uimahallin avaamiseksi", "supplementary"),
    ]
    texts = [s.text for s in item.sections] + [item.title]
    assert not any(contains_pii(t) for t in texts)
    assert not any("Edellinen asia" in t or "Muutoksenhakuohje" in t for t in texts)


def test_vote_pdf_layout_one_matches_prose():
    item = olari()
    assert len(item.votes) == 1  # the section's vote in Päätöshistoria is not this body's
    v = item.votes[0]
    assert v.counts.model_dump() == {"jaa": 30, "ei": 41, "tyhja": 4, "poissa": 0}
    assert len(v.ballots) == 75 and not v.needs_review, v.review_reason
    assert (v.jaa_label, v.ei_label, v.source) == ("Esimerkki", "vastaan", "pdf")
    assert v.source_url == "https://espoo.oncloudos.com/kokous/20261715-13-375914.PDF"
    assert v.result_text.startswith("Äänestyksessä valtuusto 30 äänellä 41 ääntä vastaan")
    assert any(b.person_ref.raw == "af Testsson Jouni J." for b in v.ballots)
    (motion,) = item.motions
    assert (motion.kind, motion.proposer_ref.raw, [s.raw for s in motion.seconder_refs]) == (
        "resolution", "Esimerkki", ["Mallisen"])  # fmt: skip
    assert motion.text.startswith("Valtuusto toivoo") and motion.outcome == "rejected"


def test_vote_pdf_layout_two_six_votes():
    item = adapter().fetch_item(item_ref("20251553", 3, "espoo/valtuusto/2025-12-08", 167))
    assert [(v.counts.jaa, v.counts.ei, v.counts.tyhja) for v in item.votes] == [
        (38, 36, 1), (34, 39, 2), (40, 33, 2), (35, 38, 2), (39, 34, 2), (44, 31, 0)]  # fmt: skip
    assert all(len(v.ballots) == 75 and not v.needs_review for v in item.votes), [
        v.review_reason for v in item.votes
    ]
    assert [v.jaa_label for v in item.votes] == ["Immonen", "Hopsu 3.2", "Hopsu 3.3.", "Nurminen",
                                                 "Nevanlinna 3.6", "Nevanlinna 3.7"]  # fmt: skip
    # a deputy printed on two lines with the member they replace
    assert any(b.person_ref.raw == "Varamies Ville" for b in item.votes[1].ballots)
    # the duplicate attachment list without links is skipped
    assert [a.title for a in item.attachments] == ["Liite 1 Äänestyslistat § 167"]


def test_agenda_item_has_no_votes_or_motions():
    item = adapter().fetch_item(item_ref("20261743", 1, "espoo/valtuusto/2026-10-19", None, Stage.agenda))
    assert item.votes == [] and item.motions == [] and item.pykala is None
    assert [s.type for s in item.sections] == ["proposal"]


def test_prose_counts_differing_from_pdf_need_review():
    site = FakeEspoo()
    html = (
        (FIXTURES / "item-20261715-13.html")
        .read_text(encoding="utf-8")
        .replace("30 äänellä 41", "31 äänellä 40")
    )
    site.overrides["/cgi/DREQUEST.PHP?page=meetingitem&id=20261715-13"] = (
        "text/html; charset=UTF-8",
        html.encode(),
    )
    (v,) = olari(site).votes
    assert v.needs_review and "minutes text says 31–40" in v.review_reason
    assert len(v.ballots) == 75  # ballots still come from the PDF


def test_missing_vote_pdf_keeps_prose_counts():
    site = FakeEspoo()
    site.status["/kokous/20261715-13-375914.PDF"] = 404
    (v,) = olari(site).votes
    assert v.counts.model_dump() == {"jaa": 30, "ei": 41, "tyhja": 4, "poissa": 0}
    assert v.ballots == [] and v.needs_review and "not found" in v.review_reason


def test_failing_vote_pdf_is_retried_later():
    site = FakeEspoo()
    site.status["/kokous/20261715-13-375914.PDF"] = 500
    with pytest.raises(TransientItemError):
        olari(site)


def test_golden_vote_item(request):
    path = GOLDEN / "item-20261715-13.json"
    data = jsonio.dumps(olari())
    if request.config.getoption("--update-goldens"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    assert path.read_bytes() == data


# -- PDF and prose units --------------------------------------------------------------------


def test_prose_number_words_and_no_blank():
    (a, b) = vc.parse_prose([
        "Puheenjohtaja totesi jaoston 4 äänellä 4 ääntä vastaan yhden äänestäessä tyhjää hyväksyneen ehdotuksen.",
        "Äänestyksessä kaupunginhallitus 8 äänellä kolmea ääntä vastaan hylkäsi ehdotuksen.",
    ])  # fmt: skip
    assert (a.a, a.b, a.tyhja) == (4, 4, 1) and (b.a, b.b, b.tyhja) == (8, 3, 0)


def test_legend_variants():
    assert vc.parse_legend("Nevanlinna Jaa / vastaan Ei / Tyhjä") == ("Nevanlinna", "vastaan")
    assert vc.parse_legend("Jaa: Immonen / Ei: vastaan / Tyhjä") == ("Immonen", "vastaan")
    assert vc.parse_legend("Jaa Hopsu 3.3. / Ei: vastaan / Tyhjä") == ("Hopsu 3.3.", "vastaan")
    assert vc.parse_legend("Jaa / pohjaehdotus / Ei / 6.2 / Tyhjä") == ("pohjaehdotus", "6.2")


def test_pdf_lines_ei_aanestanyt_is_poissa():
    (v,) = vc.parse_vote_pdf_lines([
        "Cloudmeeting Äänestystulosraportti", "1. Äänestys: Jaa / pohjaehdotus / Ei / 6.2 / Tyhjä",
        "Annettuja ääniä yhteensä 3", "Äänet vaihtoehdoittain", "Jaa 2", "Ei 1", "Ei äänestänyt 1",
        "Äänet äänestäjittäin", "Malli Matti Jaa", "Näyte Nina Jaa", "Kokeilu Kalle Ei",
        "Luonnos Liisa (Ei äänestänyt)",
    ])  # fmt: skip
    assert (v.jaa_label, v.ei_label) == ("pohjaehdotus", "6.2")
    assert v.counts == {"jaa": 2, "ei": 1, "poissa": 1}
    assert v.ballots[-1] == ("Luonnos Liisa", "poissa") and v.leftover == []
    (ev,) = vc.build_votes([], [v], item_url="u", pdf_url="p")
    assert ev.counts.poissa == 1 and ev.needs_review and "no matching vote sentence" in ev.review_reason


# -- crawl ----------------------------------------------------------------------------------


def run(tmp_path, site=None, **kw):
    site = site or FakeEspoo()
    (tmp_path / "config" / "bodies").mkdir(parents=True, exist_ok=True)
    report = crawl(DynastyAdapter(client(site)), "espoo", since=dt.date(2025, 1, 1), today=TODAY,
                   data_dir=tmp_path / "data", config_dir=tmp_path / "config", **kw)  # fmt: skip
    return report, site


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_full_crawl_writes_meetings_and_validates(tmp_path):
    report, site = run(tmp_path)
    assert report.alarms == [] and report.parse_errors == 0
    data = tmp_path / "data"
    files = sorted(p.name for p in (data / "espoo" / "meetings").rglob("*.json"))
    assert files == ["valtuusto--2025-12-08.json", "valtuusto--2026-09-21.json", "valtuusto--2026-10-19.json"]
    mf = jsonio.read(data / "espoo" / "meetings" / "2026" / "valtuusto--2026-09-21.json")
    assert [len(i["votes"]) for i in mf["items"]] == [0, 0, 1]
    assert not any("keskusvaalilautakunta" in r and "page=meetings" in r for r in site.requests)
    yaml_text = (tmp_path / "config" / "bodies" / "espoo.yaml").read_text(encoding="utf-8")
    assert "keskusvaalilautakunta:" in yaml_text and "excluded_by_rule: true" in yaml_text
    r = validate_city("espoo", data)
    assert r.ok and r.warnings == [], (r.errors, r.warnings)


def test_second_run_produces_no_diff(tmp_path):
    run(tmp_path)
    before = snapshot(tmp_path)
    report, _ = run(tmp_path)
    assert report.files_changed == 0
    assert snapshot(tmp_path) == before
