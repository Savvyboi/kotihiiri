import datetime as dt
from collections import Counter

from kunta import jsonio
from kunta.adapters import NotEnabled, adapter_for
from kunta.adapters.tweb import TwebAdapter
from kunta.crawl import crawl
from kunta.models import ItemRef, Stage
from kunta.parsers import tweb as tp
from kunta.pdf import pdf_pages
from kunta.text import contains_pii
from kunta.validate import validate_city
from tests.vantaa_site import FIXTURES, FakeVantaa, client

SITE = "https://paatokset.vantaa.fi"
TODAY = dt.date(2026, 10, 13)
COUNCIL = "vantaa/kaupunginvaltuusto"


def adapter(site=None):
    return TwebAdapter(client(site or FakeVantaa()))


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def doc(docid: str) -> list[str]:
    return [ln for page in pdf_pages((FIXTURES / f"doc-{docid}.pdf").read_bytes()) for ln in page]


def council_items(date: str, bid: str):
    a = adapter()
    body = next(b for b in a.discover_bodies() if b.id == COUNCIL)
    ref = next(r for r in a.list_meetings(body, dt.date(2025, 1, 1), None) if r.source_ids["bid"] == bid)
    meeting = a.fetch_meeting(ref)
    assert meeting.date.isoformat() == date
    return a, meeting, {r.pykala: r for r in a.item_refs(meeting)}


# -- bodies and listings --------------------------------------------------------------------


def test_bodies_from_the_dropdown_with_exclude_rules():
    bodies = {b.id: b for b in adapter().discover_bodies()}
    council = bodies[COUNCIL]
    assert (council.kind, council.included, council.source_ids) == ("council", True, {"kirjaamo": "55038"})
    assert bodies["vantaa/kaupunginhallitus"].source_ids == {"kirjaamo": "55015"}
    assert bodies["vantaa/kaupunkiymparistolautakunta"].included
    assert bodies["vantaa/konsernijaosto"].kind == "section"
    # Swedish duplicate of the council, regional committees, follow-up groups, election board,
    # the permit section and test bodies stay out (§7.4)
    for slug in ("stadsfullmaktige", "aviapoliksen-aluetoimikunta", "keskusvaalilautakunta",
                 "kaupunkiymparistolautakunnan-lupajaosto", "astan-testitoimielin",
                 "hakunila-lansimaen-kaupunkikeskusten-seurantaryhma"):  # fmt: skip
        assert not bodies[f"vantaa/{slug}"].included, slug


def test_meeting_list_merges_minutes_and_upcoming_agendas():
    a = adapter()
    body = next(b for b in a.discover_bodies() if b.id == COUNCIL)
    refs = a.list_meetings(body, dt.date(2025, 1, 1), None)
    assert [(r.date.isoformat(), r.stage, r.source_ids["bid"]) for r in refs] == [
        ("2025-11-17", "minutes", "160586"),
        ("2026-09-21", "minutes", "161950"),
        ("2026-10-19", "agenda", "161954"),
    ]
    assert refs[1].source_url == f"{SITE}/ktwebscr/pk_asil_tweb.htm?bid=161950"
    assert refs[2].source_url == f"{SITE}/ktwebscr/epj_asil_tweb.htm?bid=161954"
    # older rows are listed back to 2014 but filtered by `since`
    assert len(a.list_meetings(body, dt.date(2014, 1, 1), None)) == 5


def test_meeting_rows_without_pykala_are_not_items():
    page = tp.parse_meeting(html("meeting-161913.html"))
    assert page.compiled_pdf == f"{SITE}/ktwebscr/fileshow?doctype=3&docid=3466466"
    assert page.cover_pdf == f"{SITE}/ktwebscr/fileshow?doctype=3&docid=3461024"
    assert [r.pykala for r in page.rows] == list(range(1, len(page.rows) + 1))
    assert [r.ordinal for r in page.rows] == [r.pykala for r in page.rows]
    titles = [r.title for r in page.rows]
    assert not any("kansilehti" in t or t.startswith("Muutoksenhakuohje") for t in titles)
    # presenter initials dropped from board titles ("/ PT", "/PT (kvalt)", "/ TeA")
    assert titles[4] == "Talouden seuranta"
    assert not any(t.endswith(("/PT", "/ PT", "(kvalt)", "/ TeA")) for t in titles)
    row = next(r for r in page.rows if r.docid == "3461044")
    assert row.attachments_url == f"{SITE}/ktwebscr/pk_attn_tweb.htm?id=3461044"


# -- cover page -----------------------------------------------------------------------------


def test_council_cover_page_two_columns_roles_and_notes():
    cover = tp.parse_cover(doc("3460149"))
    assert (cover.date, cover.start_time, cover.end_time) == (dt.date(2026, 9, 21), "18:05", "23:18")
    assert cover.location == "Kaupungintalo, Asematie 7, 01300 Vantaa"
    by_role = Counter(p.role for p in cover.participants)
    assert (
        by_role["jäsen"]
        + by_role["puheenjohtaja"]
        + by_role["I varapuheenjohtaja"]
        + by_role["II varapuheenjohtaja"]
        == 67
    )
    assert by_role["varajäsen"] == 8
    people = {p.name: p for p in cover.participants}
    assert people["Rokkanen Sakari"].role == "puheenjohtaja"
    assert not people["Ahava Marja"].present and not people["Suoniemi Juha"].present
    assert people["Raja-Aho Maarit"].present  # a hyphen in a name is not the absent mark
    assert people["el Issaoui Naima"].present
    assert people["Minna Räsänen"].note == "klo 18.05-19.35 § 1-6"
    assert people["Iina Pajuvuo"].role == "hallintoasiantuntija, pöytäkirjanpitäjä"
    assert not people["Pennanen Sari-Anna"].present


def test_compiled_minutes_cover_after_the_table_of_contents():
    cover = tp.parse_cover(doc("3291113"))
    assert (cover.date, cover.start_time, cover.end_time) == (dt.date(2025, 11, 17), "13:00", "00:22")
    people = {p.name: p for p in cover.participants}
    # notes cut by the next column: "(pj § 1-6, 13.00- Lahti Timo x"
    assert people["Rokkanen Sakari"].note == "pj § 1-6, 13.00-" and people["Lahti Timo"].present
    assert not people["Lindtman Antti"].present
    assert people["Viilo Mikko"].role == "varajäsen"


def test_board_cover_page_ignores_the_unmarked_deputy_column():
    cover = tp.parse_cover(doc("3461024"))
    assert (cover.start_time, cover.end_time) == ("14:07", "15:55")
    names = {p.name for p in cover.participants}
    assert "Kaukola Ulla" in names and "Laakso Päivi" not in names
    assert next(p for p in cover.participants if p.name == "Aura Anssi").note == "klo 14.09–"
    assert sum(p.role in ("jäsen", "puheenjohtaja", "I varapuheenjohtaja", "II varapuheenjohtaja")
               for p in cover.participants) == 15  # fmt: skip


# -- items ----------------------------------------------------------------------------------


def test_item_pdf_split_into_history_and_the_meetings_own_block():
    d = tp.parse_item_lines(
        doc("3263229"), "Vantaan kaupungin tulovero- ja kiinteistöveroprosentit vuonna 2026"
    )
    assert d.case_number == "VD/7118/02.03.00.00/2025"
    assert [b.header for b in d.blocks] == [
        "Kaupunginhallitus 4.11.2025 § 7",
        "Kaupunginvaltuusto 17.11.2025 § 10",
    ]
    assert d.attachment_titles == ["äänestysraportti kv 17.11.2025 § 10"]
    sections, statements, deliberation = tp.item_sections(d)
    assert [(s.type, s.heading) for s in sections] == [
        ("background", None),
        ("history", "Kaupunginhallitus 4.11.2025 § 7"),
        ("proposal", "Kaupunginhallituksen esitys"),
        ("deliberation", "Käsittely"),
        ("decision", "Päätös"),
    ]
    assert sections[-1].text.startswith("Hyväksyttiin esitys.")
    # contact lines after "Lisätiedot:" are dropped
    assert not any(contains_pii(s.text) or "[at]" in s.text for s in sections)
    assert any("Eerola" in ln for ln in deliberation)


def test_statements_and_dissents_split_off_the_decision():
    d = tp.parse_item_lines(doc("3263227"), "Talousarvio 2026 ja taloussuunnitelma 2026–2029")
    _, statements, _ = tp.item_sections(d)
    assert [s.type for s in statements] == ["dissent", "dissent", "statement", "statement"]
    assert statements[0].text.startswith("Merkittiin, että valtuutettu Janne Hartikainen jätti")


def test_procedural_item_without_diary_number():
    d = tp.parse_item_lines(doc("3460153"), "Kokouksen laillisuus ja päätösvaltaisuus")
    assert d.case_number is None
    assert d.background[0].startswith("Kuulutus valtuuston kokouksesta")
    assert [b.header for b in d.blocks] == ["Kaupunginvaltuusto 21.9.2026 § 1"]


def test_motions_with_seconders_unseconded_and_outcomes_from_the_votes():
    d = tp.parse_item_lines(doc("3263227"))
    motions, prose = tp.parse_case(tp.item_sections(d)[2])
    assert [(m.kind, m.proposer_ref.raw, [s.raw for s in m.seconder_refs], m.outcome) for m in motions] == [
        ("send_back", "Petri Roininen", ["Janne Hartikainen"], "rejected"),
        ("counter_proposal", "Loviisa Kaartokallio", ["Tiina Tuomelan"], "rejected"),
        ("counter_proposal", "Chau Nguyen", ["Minttu Sillanpään"], "rejected"),
        ("counter_proposal", "Loviisa Kaartokallio", ["Tiina Tuomelan"], "rejected"),
        ("counter_proposal", "Chau Nguyen", ["Minttu Sillanpään"], "rejected"),
        ("counter_proposal", "Heli Hakala", ["Kaartokallion"], "rejected"),
    ]
    assert motions[0].text == "asian palautusta valmisteluun."
    assert [(p.a, p.b, p.tyhja) for p in prose] == [(55, 12, 0), (55, 12, 0), (59, 8, 0), (53, 12, 1),
                                                     (61, 6, 0), (36, 31, 0)]  # fmt: skip
    assert (prose[0].jaa_label, prose[0].ei_label) == (
        "asian käsittelyn jatkamista",
        "Roinisen palautusesitys",
    )
    # the board's block: an unseconded motion lapses; voters' surnames in brackets
    d.blocks = d.blocks[:1]
    motions, prose = tp.parse_case(tp.item_sections(d)[2])
    assert [(m.proposer_ref.raw, m.seconder_refs == [], m.outcome) for m in motions] == [
        ("Ville Karinen", True, "rejected"),
        ("Petri Roininen", False, "rejected"),
        ("Mika Kasonen", False, "rejected"),
    ]
    assert prose[1].names["ei"] == [
        "Hakala",
        "Kasonen",
        "Kivimäki",
        "Niikko",
        "Roininen",
        "Snellman",
        "Vacker",
    ]


def test_vote_report_blocks_with_parties():
    votes = tp.parse_vote_report(doc("3265562"))
    assert [(v.pykala, v.date.isoformat(), v.jaa_label, v.ei_label) for v in votes][:2] == [
        (9, "2025-11-17", "käsittelyn jatkaminen", "palautus"),
        (9, "2025-11-18", "pohja", "Kaartokallion muutosesitys"),  # past midnight
    ]
    assert [(v.counts["jaa"], v.counts["ei"], v.counts["tyhja"]) for v in votes] == [
        (55, 12, 0), (55, 12, 0), (59, 8, 0), (54, 12, 1), (61, 6, 0), (36, 31, 0)]  # fmt: skip
    for v in votes:
        got = Counter(c for _, c in v.ballots)
        assert all(got.get(c, 0) == n for c, n in v.counts.items()), v
        assert not v.leftover and len(v.groups) == v.total == 67
    assert ("Gashaw Kaisa Bibani", "ei") in tp.parse_vote_report(doc("3265564"))[0].ballots
    assert tp.parse_vote_report(doc("3265564"))[0].groups["Naima el Issaoui"] == "sdp"


def test_council_item_votes_from_the_report_only_for_this_meeting():
    a, _, refs = council_items("2025-11-17", "160586")
    item = a.fetch_item(refs[9])
    assert [att.title for att in item.attachments][:2] == [
        "Kaupunginhallituksen esitys talousarvioksi 2026 ja taloussuunnitelmaksi 2026–2029, kv 17.11.2025 § 9",
        "Äänestysraportti kv 17.11.2025 § 9",
    ]
    # the board's reports ("Äänestysraportti KH 4.11.2025 § 6 …") are attached too but not this vote
    assert len(item.votes) == 6
    v = item.votes[0]
    assert (v.jaa_label, v.ei_label, v.source, v.needs_review) == (
        "käsittelyn jatkaminen",
        "palautus",
        "pdf",
        False,
    )
    assert v.source_url == f"{SITE}/ktwebscr/fileshow?doctype=3&docid=3265562&version=1"
    assert v.ballots[0].model_dump(exclude={"person_ref"}) == {"choice": "jaa", "group_text": "sdp"}
    # the minutes text and the report disagree on one ballot: flagged with both sides
    flagged = [x for x in item.votes if x.needs_review]
    assert [x.ordinal for x in flagged] == [4]
    assert "53–12, 1 blank" in flagged[0].review_reason and "54 Jaa" in flagged[0].review_reason
    assert all(m.outcome == "rejected" for m in item.motions)


def test_items_without_vote_report_keep_prose_counts_and_board_names():
    a = adapter()
    ref = ItemRef(meeting_id="vantaa/kaupunginhallitus/2025-11-04", ordinal=6, pykala=6,
                  source_url=f"{SITE}/ktwebscr/fileshow?doctype=3&docid=3263227",
                  source_ids={"docid": "3263227"}, stage=Stage.minutes, title="Talousarvio")  # fmt: skip
    item = a.fetch_item(ref)
    # the document also carries the council's later handling; the board's own block is read,
    # whose sentences name the voters: ballots from the names, no report needed
    assert [(v.counts.jaa, v.counts.ei, v.source, v.needs_review) for v in item.votes] == [
        (13, 2, "html", False),
        (8, 7, "html", False),
    ]
    v = item.votes[1]
    assert (v.jaa_label, v.ei_label) == ("kaupunginjohtajan esitys", "Kasosen muutosesitys")
    assert [b.person_ref.raw for b in v.ballots if b.choice == "ei"][:2] == ["Hakala", "Kasonen"]
    assert [m.outcome for m in item.motions] == ["rejected", "rejected", "rejected"]


def test_agenda_stage_items_have_no_votes_or_pykala():
    a = adapter()
    body = next(b for b in a.discover_bodies() if b.id == COUNCIL)
    ref = a.list_meetings(body, dt.date(2026, 10, 1), None)[0]
    meeting = a.fetch_meeting(ref)
    assert (meeting.stage, meeting.attendance, meeting.minutes_pdf_url) == ("agenda", [], None)
    item = a.fetch_item(a.item_refs(meeting)[0])
    assert (item.pykala, item.votes, item.motions) == (None, [], [])


def test_missing_attachment_page_does_not_fail_the_item():
    site = FakeVantaa()
    site.status["/ktwebscr/pk_attn_tweb.htm?id=3263229"] = 404
    a, _, refs = council_items("2025-11-17", "160586")
    a.client = client(site)
    item = a.fetch_item(refs[10])
    assert item.attachments == [] and item.votes[0].needs_review


def test_oulu_shares_the_adapter_but_stays_disabled():
    try:
        adapter_for("oulu", client(FakeVantaa()))
    except NotEnabled:
        pass
    else:
        raise AssertionError("Oulu must stay disabled (§2)")


# -- crawl ----------------------------------------------------------------------------------


def test_full_crawl_writes_meetings_and_validates(tmp_path):
    site = FakeVantaa()
    (tmp_path / "config" / "bodies").mkdir(parents=True, exist_ok=True)
    report = crawl(TwebAdapter(client(site)), "vantaa", since=dt.date(2025, 1, 1), today=TODAY,
                   data_dir=tmp_path / "data", config_dir=tmp_path / "config")  # fmt: skip
    assert report.parse_errors == 0
    data = tmp_path / "data" / "vantaa" / "meetings"
    assert sorted(p.name for p in data.rglob("*.json")) == [
        "kaupunginhallitus--2026-09-21.json",
        "kaupunginhallitus--2026-10-05.json",
        "kaupunginvaltuusto--2025-11-17.json",
        "kaupunginvaltuusto--2026-09-21.json",
        "kaupunginvaltuusto--2026-10-19.json",
    ]
    mf = jsonio.read(data / "2026" / "kaupunginvaltuusto--2026-09-21.json")
    assert len(mf["meeting"]["attendance"]) == 88 and len(mf["items"]) == 27
    assert not any("Stadsfullm" in r or "55000" in r for r in site.requests)
    # 17.11.2025 has no cover page row; its attendance comes from the compiled minutes' first pages
    mf = jsonio.read(data / "2025" / "kaupunginvaltuusto--2025-11-17.json")
    assert (mf["meeting"]["start_time"], mf["meeting"]["end_time"]) == ("13:00", "00:22")
    assert len(mf["meeting"]["attendance"]) == 93
    r = validate_city("vantaa", tmp_path / "data")
    assert r.ok and r.warnings == [], (r.errors, r.warnings)
