import datetime as dt
from pathlib import Path

from kunta import jsonio
from kunta.adapters.casem import CasemAdapter
from kunta.crawl import crawl
from kunta.models import ItemRef, MeetingRef, Stage
from kunta.parsers import casem as cp
from kunta.parsers import votes_casem as vc
from kunta.text import contains_pii, is_confidential
from kunta.validate import validate_city
from tests.tampere_site import FIXTURES, FakeTampere, client

GOLDEN = Path(__file__).resolve().parent / "golden" / "tampere"
SITE = "https://tampere.cloudnc.fi"
TODAY = dt.date(2026, 10, 13)
COUNCIL = "tampere/kaupunginvaltuusto"


def adapter(site=None):
    return CasemAdapter(client(site or FakeTampere()))


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def item_ref(
    key: str, ordinal: int, pykala: int | None, stage=Stage.minutes, meeting=f"{COUNCIL}/2025-11-10"
):
    return ItemRef(meeting_id=meeting, ordinal=ordinal, source_url=f"{SITE}/fi-FI/content/{key}",
                   source_ids={"item": key}, stage=stage, title="Otsikko", pykala=pykala)  # fmt: skip


def budget():
    return adapter().fetch_item(item_ref("476107/35325", 8, 176))


# -- bodies and listings --------------------------------------------------------------------


def test_discover_bodies_drop_discontinued_marker_and_apply_exclude_rules():
    bodies = {b.id: b for b in adapter().discover_bodies()}
    assert len(bodies) == 36
    council = bodies[COUNCIL]
    assert (council.kind, council.included, council.source_ids) == (
        "council",
        True,
        {"slug": "Kaupunginvaltuusto"},
    )
    # "Z/Sosiaali- ja terveyslautakunta": id and name without the marker, slug as the site spells it
    sote = bodies["tampere/sosiaali-ja-terveyslautakunta"]
    assert (sote.name_fi, sote.source_ids["slug"]) == (
        "Sosiaali- ja terveyslautakunta",
        "ZSosiaali_ja_terveyslautakunta",
    )
    assert (
        bodies["tampere/asunto-ja-kiinteistolautakunta"].source_ids["slug"]
        == "Asunto_ja_kiinteistoumllautakunta"
    )
    assert bodies["tampere/kaupunginvaltuuston-kyselytunti"].kind == "council"
    for excluded in ("keskusvaalilautakunta", "tampereen-nuorisovaltuusto", "testitoimielin", "vanhusneuvosto",
                     "maahanmuuttajaneuvosto", "elakelaisvaltuusto", "versiopaivitystoimielin"):  # fmt: skip
        assert not bodies[f"tampere/{excluded}"].included, excluded


def test_listing_dates_come_from_link_text_and_the_agenda_line():
    rows = cp.parse_meetings(fixture("body-Kaupunginvaltuusto.html"))
    agenda, minutes = rows
    assert (agenda.meeting_key, agenda.date, agenda.stage) == (
        "Kokous_19102026",
        dt.date(2026, 10, 19),
        "agenda",
    )
    assert (agenda.start_time, agenda.location) == ("17:00", "Kaupungintalo, Valtuustosali")
    assert (minutes.meeting_key, minutes.date, minutes.stage) == (
        "Kokous_10112025",
        dt.date(2025, 11, 10),
        "minutes",
    )


def test_minutes_meeting_attendance_in_three_groups():
    a = adapter()
    ref = MeetingRef(body_id=COUNCIL, date=dt.date(2025, 11, 10), stage=Stage.minutes,
                     source_url=f"{SITE}/fi-FI/Toimielimet/Kaupunginvaltuusto/Kokous_10112025",
                     source_ids={"meeting": "Kokous_10112025"})  # fmt: skip
    m = a.fetch_meeting(ref)
    assert m.minutes_pdf_url.startswith(f"{SITE}/download/noname/")
    assert len(m.items) == 16
    refs = a.item_refs(m)
    assert (refs[0].pykala, refs[0].title, refs[0].source_ids) == (169, "Kokouksen laillisuus ja päätösvaltaisuus",
                                                                   {"item": "476092/35325"})  # fmt: skip
    present = [x for x in m.attendance if x.present]
    absent = [x for x in m.attendance if not x.present]
    assert (len(m.attendance), len(present), len(absent)) == (98, 94, 4)
    chair = m.attendance[0]
    assert (chair.person_ref.raw, chair.role_text, chair.note) == (
        "Kummola Kalervo", "Puheenjohtaja", "puheenjohtajana 9:00-13:00 ja 15:18-19:10")  # fmt: skip
    assert any(x.person_ref.raw == "Heikkilä Lasse" and x.role_text == "Varajäsen" for x in present)
    assert any(
        x.person_ref.raw == "Kaunisto Kalle" and x.role_text == "hallintosihteeri, Sihteeri" for x in present
    )
    assert absent[0].person_ref.raw == "Nevanperä Lauri"


def test_agenda_meeting_has_no_attendance_or_pykala():
    a = adapter()
    a.list_meetings(next(b for b in a.discover_bodies() if b.id == COUNCIL), dt.date(2025, 1, 1), None)
    ref = MeetingRef(body_id=COUNCIL, date=dt.date(2026, 10, 19), stage=Stage.agenda,
                     source_url=f"{SITE}/fi-FI/Toimielimet/Kaupunginvaltuusto/Kokous_19102026",
                     source_ids={"meeting": "Kokous_19102026"})  # fmt: skip
    m = a.fetch_meeting(ref)
    assert (m.stage, m.attendance, m.minutes_pdf_url) == ("agenda", [], None)
    assert (m.start_time, m.location) == ("17:00", "Kaupungintalo, Valtuustosali")
    assert all(r.pykala is None for r in a.item_refs(m))


# -- items ----------------------------------------------------------------------------------


def test_council_item_history_and_attachments():
    item = adapter().fetch_item(item_ref("476105/35325", 7, 175))
    assert [s.type for s in item.sections] == ["proposal", "decision", "history"]
    assert item.sections[2].heading == "Kaupunginhallitus, 27.10.2025"
    assert item.case_number == "TRE:5412/02.03.01/2025"
    assert item.preparers == ["Linnamaa Reija", "Koskela Mikko"]
    assert [a.title for a in item.attachments] == [
        "Kh 27.10.2025 Verovuoden 2025 tulovero- ja kiinteistöveroprosenttien vertailu sisältäen kuusi suurinta "
        "kaupunkia ja Pirkanmaan kunnat.pdf"
    ]
    assert item.attachments[0].url.startswith(f"{SITE}/download/noname/")
    texts = [s.text for s in item.sections]
    assert not any(contains_pii(t) for t in texts)
    assert not any("Valitusosoitus" in t or "Valmistelijan yhteystiedot" in t for t in texts)


def test_board_item_presenter_and_background():
    item = adapter().fetch_item(
        item_ref("469538/35038", 5, 447, meeting="tampere/kaupunginhallitus/2025-10-27")
    )
    assert item.presenter == "Yli-Rajala Juha, Konsernijohtaja"
    assert [s.type for s in item.sections] == ["background", "proposal", "decision", "deliberation"]
    proposal = next(s for s in item.sections if s.type == "proposal")
    assert (
        proposal.text.startswith("Esitetään valtuuston päätettäväksi") and "Esittelijä" not in proposal.text
    )


def test_confidential_item_keeps_its_marker():
    item = adapter().fetch_item(
        item_ref("469540/35038", 12, 454, meeting="tampere/kaupunginhallitus/2025-10-27")
    )
    assert item.title == "Rikosoikeudellinen arviointi (Salassa pidettävä)" and is_confidential(item.title)
    assert item.sections == [] and item.votes == []


def test_agenda_item_has_proposal_only():
    item = adapter().fetch_item(
        item_ref("522031/37342", 1, None, Stage.agenda, meeting=f"{COUNCIL}/2026-10-19")
    )
    assert item.pykala is None and item.votes == [] and item.motions == []
    assert [s.type for s in item.sections] == ["proposal"]


def test_inline_ballots_match_counts_and_minutes_text():
    item = budget()
    assert len(item.votes) == 19
    assert all(not v.needs_review for v in item.votes), [v.review_reason for v in item.votes]
    first = item.votes[0]
    assert (first.jaa_label, first.ei_label) == (
        "Kaupunginhallituksen ehdotus",
        "Muutosehdotuksen hyväksyminen",
    )
    assert first.counts.model_dump() == {"jaa": 61, "ei": 5, "tyhja": 0, "poissa": 0}
    assert len(first.ballots) == 66 and first.source == "html"
    assert (
        first.result_text
        == "Juho Hirvelän muutosehdotus 1: Äänestyksen tulos: Muutosehdotus hylättiin äänin 61-5."
    )
    assert {b.person_ref.raw for b in first.ballots if b.choice == "ei"} == {
        "Vigelius Joakim", "Hirvelä Juho", "Kaleva Lassi", "Puolimatka Marika", "Heikkilä Lasse"}  # fmt: skip
    # two members left for a conflict of interest: only the minutes text has them, as "poissa 2"
    conflict = next(v for v in item.votes if v.result_text.startswith("Juho Hirvelän muutosehdotus 10:"))
    assert (
        conflict.counts.model_dump() == {"jaa": 59, "ei": 5, "tyhja": 0, "poissa": 0}
        and len(conflict.ballots) == 64
    )
    assert conflict.result_text.endswith("äänin 59-5, poissa 2.") and not conflict.needs_review
    # blocks are in voting order, not in the order the motions are written
    assert item.votes[6].result_text.startswith("Lasse Heikkilän muutosehdotus 1:")
    assert item.votes[-1].counts.model_dump() == {"jaa": 62, "ei": 4, "tyhja": 0, "poissa": 0}


def test_motions_from_the_minutes_text():
    item = budget()
    motions = item.motions
    assert len(motions) == 20
    helimo = motions[0]
    assert (helimo.proposer_ref.raw, [s.raw for s in helimo.seconder_refs], helimo.outcome) == (
        "Matti Helimo", ["Pilvi Kuitu"], "adopted")  # fmt: skip
    assert helimo.text.startswith("Lisätään kolme muutosta yhtiöiden tavoitteisiin:")
    hirvela = [m for m in motions if m.proposer_ref.raw == "Juho Hirvelä"]
    assert len(hirvela) == 14 and all(m.outcome == "rejected" for m in hirvela)
    assert hirvela[0].text.startswith("Muutosehdotus 1: sivu 5 Kaupunki kasvaa ja kehittyy")
    assert "äänestysesitys" not in hirvela[0].text
    assert [s.raw for s in hirvela[0].seconder_refs] == ["Marika Puolimatka"]
    assert (hirvela[-1].kind, hirvela[-1].text) == ("other", "Hylkäysehdotus")
    # renewed by Lasse Heikkilä after the original proposer left: recorded under him, as the votes are
    heikkila = [m for m in motions if m.proposer_ref.raw == "Lasse Heikkilä"]
    assert len(heikkila) == 5 and [s.raw for s in heikkila[0].seconder_refs] == ["Marika Puolimatka"]


def test_vote_counts_differing_from_the_text_need_review():
    html = fixture("item-476107-35325.html").replace("Kyllä 61 kpl 92%", "Kyllä 60 kpl 92%", 1)
    page = cp.parse_item(html)
    _, drafts = vc.parse_motions(page.deliberation_lines)
    first = vc.build_votes(page.votes_html, drafts, "u")[0]
    assert first.needs_review
    assert first.review_reason == "jaa: 61 names for 60 votes; minutes text says 61–5, the vote list 60–5"


def test_genitive_matching():
    assert vc.is_genitive_of("Juho Hirvelän", "Juho Hirvelä")
    assert vc.is_genitive_of("Sirpa Pursiainen-Hautalan", "Sirpa Pursiainen-Hautala")
    assert vc.is_genitive_of("Ville Virtasen", "Ville Virtanen")
    assert not vc.is_genitive_of("Juho Hirvelän", "Jussi Hirvelä")


def test_golden_budget_item(request):
    path = GOLDEN / "item-476107-35325.json"
    data = jsonio.dumps(budget())
    if request.config.getoption("--update-goldens"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    assert path.read_bytes() == data


# -- crawl ----------------------------------------------------------------------------------


def run(tmp_path, site=None):
    site = site or FakeTampere()
    (tmp_path / "config" / "bodies").mkdir(parents=True, exist_ok=True)
    report = crawl(CasemAdapter(client(site)), "tampere", since=dt.date(2025, 1, 1), today=TODAY,
                   data_dir=tmp_path / "data", config_dir=tmp_path / "config")  # fmt: skip
    return report, site


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_full_crawl_writes_meetings_and_validates(tmp_path):
    report, site = run(tmp_path)
    assert report.parse_errors == 0
    data = tmp_path / "data"
    files = sorted(p.name for p in (data / "tampere" / "meetings").rglob("*.json"))
    assert files == [
        "kaupunginhallitus--2025-10-27.json",
        "kaupunginvaltuusto--2025-11-10.json",
        "kaupunginvaltuusto--2026-10-19.json",
    ]
    mf = jsonio.read(data / "tampere" / "meetings" / "2025" / "kaupunginvaltuusto--2025-11-10.json")
    assert sum(len(i["votes"]) for i in mf["items"]) == 19
    assert not any("/rss/" in r for r in site.requests)
    assert not any("Keskusvaalilautakunta" in r for r in site.requests)  # excluded bodies are not listed
    r = validate_city("tampere", data)
    assert r.ok and r.warnings == [], (r.errors, r.warnings)


def test_second_run_produces_no_diff(tmp_path):
    run(tmp_path)
    before = snapshot(tmp_path)
    report, _ = run(tmp_path)
    assert report.files_changed == 0
    assert snapshot(tmp_path) == before
