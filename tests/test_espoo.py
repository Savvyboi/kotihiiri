import datetime as dt
from pathlib import Path

import pytest

from kunta import jsonio
from kunta.adapters.base import TransientItemError
from kunta.adapters.dynasty import DynastyAdapter
from kunta.crawl import crawl
from kunta.models import Body, Counts, ItemRef, MeetingRef, Stage, VoteEvent
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


# -- recorded pages -------------------------------------------------------------------------
# tests/fixtures/espoo/real: pages fetched from espoo.oncloudos.com on 2026-10-13, markup compacted.

REAL = FIXTURES / "real"


def real_item(name: str) -> dp.ItemPage:
    return dp.parse_item((REAL / f"item-{name}.html").read_text(encoding="utf-8"))


def test_real_meeting_page():
    page = dp.parse_meeting((REAL / "meeting-20251336.html").read_text(encoding="utf-8"), "20251336")
    assert (page.date, page.stage) == (dt.date(2025, 1, 20), "minutes")
    assert (page.start_time, page.end_time, page.location) == (
        "17:30",
        "19:16",
        "Valtuustotalo, Espoonkatu 5",
    )
    assert len(page.participants) == 83 and page.participants[0].role == "puheenjohtaja"
    assert page.minutes_pdf == "https://espoo.oncloudos.com/kokous/20251336.PDF"
    assert (page.rows[6].ordinal, page.rows[6].pykala) == (7, 7)


def test_real_item_inline_headings():
    # "Päätös" and its first sentence share one paragraph.
    page = real_item("20251336-1")
    assert [(s.type, s.heading) for s in page.sections] == [
        ("decision", "Päätös"),
        ("background", "Selostus"),
    ]
    assert page.sections[0].text.startswith("Puheenjohtaja totesi kokouksen laillisesti")
    assert not any("©" in s.text for s in page.sections)


def test_real_item_presenter_history_and_attachment_parts():
    page = real_item("20261715-13")
    assert (page.pykala, page.case_number, page.presenter) == (132, "1312/10.03.02/2025", "Kaupunginhallitus")
    assert page.preparers == ["Lehtinen Maija"]
    history = [s for s in page.sections if s.type == "history"]
    assert len(history) == 4 and history[0].text.startswith("Päätösehdotus Esittelijä")
    assert [(a.title, a.kind, a.url.rsplit("/", 1)[1]) for a in page.attachments] == [
        ("Liite 1 Olarin uimahallin valokuvakooste 8.6.2026", "attachment", "20261715-13-357076.PDF"),
        ("Liite 2 Äänestyslista § 132", "attachment", "20261715-13-375914.PDF"),
        ("Oheismateriaali 1 Valtuustoaloite kaupunki ryhtyisi toimiin Olarin uimahallin avaamiseksi "
         "uudelleen, Risto Nevanlinna+ 25 kvalt", "supplementary", "20261715-13-352661.PDF"),
    ]  # fmt: skip


def test_real_item_votes_with_the_vote_pdf():
    site = FakeEspoo()
    site.overrides["/cgi/DREQUEST.PHP?page=meetingitem&id=20261715-13"] = (
        "text/html; charset=UTF-8",
        (REAL / "item-20261715-13.html").read_bytes(),
    )
    item = olari(site)
    (v,) = item.votes
    assert v.counts.model_dump() == {"jaa": 30, "ei": 41, "tyhja": 4, "poissa": 0}
    assert len(v.ballots) == 75 and not v.needs_review, v.review_reason
    (motion,) = item.motions
    assert (motion.proposer_ref.raw, [s.raw for s in motion.seconder_refs]) == ("Nevanlinna", ["Aaltosen"])


def test_real_item_three_votes_in_prose():
    page = real_item("20251336-7")
    assert vc.mentions_vote_list(page.deliberation_lines)
    assert [(p.a, p.b, p.tyhja) for p in vc.parse_prose(page.deliberation_lines)] == [
        (49, 13, 13), (9, 65, 1), (32, 22, 21)]  # fmt: skip
    motions = vc.parse_motions(page.deliberation_lines)
    assert [(m.text[:5], m.proposer_ref.raw, m.outcome) for m in motions] == [
        ("7.2. ", "Halkosaari", "adopted"), ("7.3. ", "Halkosaari", "adopted"), ("7.1. ", "Hopsu", "adopted"),
        ("7.4. ", "Keronen", "rejected"), ("7.5. ", "Järvinen", "adopted")]  # fmt: skip
    assert [a.title for a in page.attachments] == [
        "Liite 1 Äänestyslista § 7",
        "Oheismateriaali 1 Valtuustokysymys Kotoutumisen edistäminen Espoossa",
    ]


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


def test_motion_title_before_seconder_and_numbered_on_one_line():
    lines = [
        "Hopsu puheenjohtaja Limnellin kannattamana ehdotti, että asia jätetään pöydälle.",
        "Hopsu Kausteen ym. kannattamana teki seuraavan toivomuksen: 9.1.",
        "Valtuusto toivoo A.",
        "Hopsu Kausteen ym. kannattamana teki seuraavan toivomuksen: 9.2.",
        "Valtuusto toivoo B.",
    ]
    table, first, second = vc.parse_motions(lines)
    assert (table.kind, [s.raw for s in table.seconder_refs], table.text) == (
        "table", ["Limnellin"], "että asia jätetään pöydälle.")  # fmt: skip
    assert (first.text, second.text) == ("9.1. Valtuusto toivoo A.", "9.2. Valtuusto toivoo B.")


def _vote(jaa_label, ei_label, jaa, ei):
    return VoteEvent(ordinal=1, jaa_label=jaa_label, ei_label=ei_label, counts=Counts(jaa=jaa, ei=ei),
                     source="pdf", source_url="u")  # fmt: skip


def test_outcomes_for_one_proposers_two_motions_and_a_send_back():
    lines = [
        "Hopsu Kausteen ym. kannattamana teki seuraavan toivomuksen: 9.1.", "Valtuusto toivoo A.",
        "Hopsu Kausteen ym. kannattamana teki seuraavan toivomuksen: 9.2.", "Valtuusto toivoo B.",
        "Puheenjohtaja tiedusteli, voidaanko Hopsun toivomusehdotus 9.1. hyväksyä yksimielisesti. Koska "
        "ehdotusta ei vastustettu, puheenjohtaja totesi valtuuston hyväksyneen sen yksimielisesti.",
        "Partanen Hagerlundin kannattamana ehdotti, että asia palautetaan uudelleen valmisteltavaksi.",
    ]  # fmt: skip
    first, second, back = vc.parse_motions(lines)
    assert (first.outcome, second.outcome, back.outcome) == ("adopted", None, None)
    # a label without a number cannot tell 9.1 from 9.2
    vc.resolve_outcomes([first, second, back], [_vote("Hopsu", "vastaan", 30, 41)])
    assert second.outcome is None
    vc.resolve_outcomes([first, second, back], [_vote("Palautus", "käsittely jatkuu", 6, 67),
                                                _vote("Hopsu 9.2", "vastaan", 30, 41)])  # fmt: skip
    assert (first.outcome, second.outcome, back.outcome) == ("adopted", "rejected", "rejected")


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


def test_prose_variants_from_the_live_crawl():
    lines = [
        "Äänestyksessä JAA ääniä tuli 6 ja EI ääniä 7. Äänestyksen jälkeen puheenjohtaja totesi "
        "kaupunkisuunnittelulautakunnan seitsemällä (7) äänellä kuutta (6) vastaan päättäneen hyväksyä muutosehdotuksen.",
        "Puheenjohtaja totesi Aaltosen ehdotuksen voittaneen seitsemällä äänellä kahta vastaan.",
        "Puheenjohtaja totesi kaupunginhallituksen 12 äänellä 2 ääntä 1 ollessa poissa vastaan hylänneen "
        "Kajavan muutosehdotuksen.",
    ]
    assert [(p.a, p.b, p.tyhja) for p in vc.parse_prose(lines)] == [(6, 7, 0), (7, 2, 0), (12, 2, 0)]


def test_vote_list_titles():
    for title in ("Äänestyslistat § 167", "Liite 3 Äänestystiedot Lahnuksen koulun korjausselvitys",
                  "Liite 3 Äänestystulosraportti §53_2026", "Liite 1 Äänestysraportti § 12"):  # fmt: skip
        assert vc.VOTE_LIST_TITLE.search(title), title
    assert not vc.VOTE_LIST_TITLE.search("Liite 1 Henttaanmylly asemakaava")


def test_pdf_votes_pair_with_prose_by_counts():
    # council 8.6.2026 § 7: the PDF lists the final vote first, the text the send-back vote first
    prose = vc.parse_prose([
        "Äänestyksessä valtuusto 4 äänellä 70 ääntä vastaan ja 1 ollessa poissa hylkäsi palautusehdotuksen.",
        "Äänestyksessä valtuusto 72 äänellä 3 ääntä vastaan hyväksyi kaupunginhallituksen ehdotuksen.",
    ])  # fmt: skip
    J, E = vc.Choice.jaa, vc.Choice.ei
    pdf = [vc.PdfVote(jaa_label="a", ei_label="b", counts={J: 72, E: 3}),
           vc.PdfVote(jaa_label="a", ei_label="b", counts={J: 4, E: 70})]  # fmt: skip
    events = vc.build_votes(prose, pdf, item_url="u", pdf_url=None)
    assert [e.result_text.split(" hy")[0] for e in events] == [
        "Äänestyksessä valtuusto 72 äänellä 3 ääntä vastaan",
        "Äänestyksessä valtuusto 4 äänellä 70 ääntä vastaan ja 1 ollessa poissa",
    ]
    assert not any("minutes text says" in (e.review_reason or "") for e in events)


def test_legend_variants_from_the_live_crawl():
    assert vc.parse_legend("Lisäsysehdotus 1 Jaa Lisäys/ Ei Pohja / Tyhjä") == ("Lisäys", "Pohja")
    assert vc.parse_legend("Äänestys: Jaa esittelijä / Ei Partanen/ Tyhjä") == ("esittelijä", "Partanen")
    assert vc.parse_legend("esittelijä Jaa / Nevanlinna Ei / Tyhjä") == ("esittelijä", "Nevanlinna")
    assert vc.parse_legend("13.1 Jaa / Ei / Tyhjä") == ("13.1", "")


# Shapes from recorded vote PDFs (konserni- ja tilajaosto 1.9.2025 § 20, kaupunkisuunnittelulautakunta
# 26.3.2025 § 49, elinkeinojaosto 3.11.2025 § 104, kaupunginhallitus 31.3.2025 § 91).
HEAD = ["Cloudmeeting Äänestystulosraportti", "Toimielin Jaosto", "Kokous Jaosto 01.09.2025", "§ 20 Lausunto"]


def test_pdf_deputy_wrapped_over_two_lines_and_annotation_lines():
    (v,) = vc.parse_vote_pdf_lines([
        *HEAD, "1. Äänestys: Muutosesitys 1 Jaa pohja / Ei muutos / Tyhjä", "Annettuja ääniä yhteensä 3",
        "Ei äänestänyt 0", "Äänet vaihtoehdoittain", "Ei 1", "Jaa 2", "Äänet äänestäjittäin",
        "Marttila Helena Ei", "Laakso Mikko (Sammallahti Jaa", "Tere)", "Stenholm Elena Jaa",
        "(Fagerström Noora)",
    ])  # fmt: skip
    assert v.ballots == [("Marttila Helena", vc.Choice.ei), ("Laakso Mikko", vc.Choice.jaa),
                         ("Stenholm Elena", vc.Choice.jaa)]  # fmt: skip
    assert (v.jaa_label, v.ei_label, v.leftover) == ("pohja", "muutos", [])


def test_pdf_option_labels_follow_the_choice():
    (v,) = vc.parse_vote_pdf_lines([
        *HEAD, "1. Äänestys: 4.1 Jaa / Ei / Tyhjä", "Annettuja ääniä yhteensä 3", "Äänet vaihtoehdoittain",
        "Jaa Asian jatkaminen 2", "Ei Palautus 1", "Tyhjä 0", "Äänet äänestäjittäin",
        "Järvinen Hannu Ei Palautus", "Särkijärvi Jouni J. Jaa Asian jatkaminen", "Kyrölä Kimmo (Laine Anna) J aa",
    ])  # fmt: skip
    assert v.counts == {vc.Choice.jaa: 2, vc.Choice.ei: 1, vc.Choice.tyhja: 0}
    assert v.ballots == [("Järvinen Hannu", vc.Choice.ei), ("Särkijärvi Jouni J.", vc.Choice.jaa),
                         ("Kyrölä Kimmo", vc.Choice.jaa)]  # fmt: skip
    assert v.jaa_label == "4.1" and v.ei_label == "Palautus"


def test_pdf_legend_printed_above_a_bare_vote_number():
    votes = vc.parse_vote_pdf_lines([
        *HEAD, "1. Äänestys: esittelijä Jaa / Nevanlinna Ei / Tyhjä", "Annettuja ääniä yhteensä 1",
        "Äänet vaihtoehdoittain", "Jaa 1", "Äänet äänestäjittäin", "Elo Simon Jaa",
        "Esittelijä Jaa / Aaltonen Ei / Tyhjä", "4. Äänestys:", "Annettuja ääniä yhteensä 1",
        "Äänet vaihtoehdoittain", "Ei 1", "Äänet äänestäjittäin", "Aaltonen Juri Ei",
    ])  # fmt: skip
    assert [(v.jaa_label, v.ei_label, len(v.ballots)) for v in votes] == [
        ("esittelijä", "Nevanlinna", 1), ("Esittelijä", "Aaltonen", 1)]  # fmt: skip


def test_absentee_listed_but_not_counted_and_unlabelled_sides_with_prose():
    (v,) = vc.parse_vote_pdf_lines([
        *HEAD, "1. Äänestys: 13.1 Jaa / Ei / Tyhjä", "Annettuja ääniä yhteensä 2", "Äänet vaihtoehdoittain",
        "Ei 1", "Jaa 1", "Äänet äänestäjittäin", "Elo Tiina Ei", "Kajava Henna Jaa", "Guzenina Maria Poissa",
    ])  # fmt: skip
    prose = vc.parse_prose(["Äänestyksessä jaosto yhdellä äänellä yhtä ääntä vastaan hyväksyi ehdotuksen."])
    (event,) = vc.build_votes(prose, [v], item_url="u", pdf_url="p")
    assert not event.needs_review, event.review_reason
