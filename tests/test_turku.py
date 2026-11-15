import datetime as dt

from kunta import jsonio
from kunta.adapters.turku import TurkuAdapter
from kunta.crawl import crawl
from kunta.models import Body, Choice, Outcome, Stage
from kunta.parsers import turku as tp
from kunta.validate import validate_city
from tests.turku_site import FIXTURES, FakeTurku, client

BASE = "https://paatokset.turku.fi"
COUNCIL = Body(id="turku/kaupunginvaltuusto", city="turku", name_fi="Kaupunginvaltuusto", kind="council",
               source_ids={"abbr": "Kv", "route": "kaupunginvaltuusto"})  # fmt: skip
TODAY = dt.date(2026, 11, 15)


def adapter(site=None):
    return TurkuAdapter(client(site or FakeTurku()), BASE)


def council_meeting(a, api_id="5481565"):
    refs = a.list_meetings(COUNCIL, dt.date(2025, 1, 1), None)
    return a.fetch_meeting(next(r for r in refs if r.source_ids["meeting_id"] == api_id))


def test_bodies_skip_swedish_twins_and_use_the_spa_route():
    bodies = {b.source_ids["abbr"]: b for b in adapter().discover_bodies()}
    assert bodies["Kv"].id == "turku/kaupunginvaltuusto" and bodies["Kv"].kind == "council"
    assert bodies["Kh"].kind == "board"
    assert "Sfm" not in bodies  # Stadsfullmäktige: same documents as Kv
    assert bodies["Khkon"].source_ids["route"] == "kaupunginhallituksen-konsernijaosto"
    assert tp.route_slug("Ympäristö- ja lupajaosto") == "ymparisto-ja-lupajaosto"


def test_listing_by_year_newest_agenda_and_minutes():
    refs = adapter().list_meetings(COUNCIL, dt.date(2025, 1, 1), None)
    assert len(refs) == 21  # 11 in 2025, 9 minutes and 1 agenda in 2026
    assert refs[-1].date == dt.date(2026, 11, 16) and refs[-1].stage == Stage.agenda
    assert refs[-2].stage == Stage.minutes and refs[-2].source_ids["number"] == "9/2026"
    assert refs[-2].source_url == f"{BASE}/kaupunginvaltuusto/5481565"


def test_meeting_items_and_attendance():
    a = adapter()
    m = council_meeting(a)
    assert (m.start_time, m.end_time, m.location) == ("18:00", "19:47", "Linnasmäen opisto, Lustokatu 7")
    refs = a.item_refs(m)
    assert [r.pykala for r in refs] == [183, 185, 186, 194]  # appeal instructions left out
    assert refs[2].source_url == f"{BASE}/kaupunginvaltuusto/5481565/5481535"
    assert len(m.attendance) == 75 and m.attendance[0].role_text == "valtuutettu"


def test_item_with_two_votes_history_and_party_per_voter():
    a = adapter()
    m = council_meeting(a)
    item = a.fetch_item(a.item_refs(m)[2])
    types = [s.type for s in item.sections]
    assert types[0] == "background" and types[-3:] == ["decision", "deliberation", "deliberation"]
    assert any(s.heading == "Kh § 315: Päätös" for s in item.sections if s.type == "history")
    assert item.case_number == "1087/2025"
    assert [a.title for a in item.attachments][-1] == "Äänestyslistat"
    assert len(item.votes) == 2
    v1, v2 = item.votes
    assert (v1.counts.jaa, v1.counts.ei, v1.counts.tyhja) == (56, 11, 0)
    assert (v1.jaa_label, v1.ei_label) == ("Ehdotus Kh", "Muutos Diop Paco")
    assert v2.ei_label == "Muutos Koiranen Sara"
    assert not v1.needs_review and not v2.needs_review
    assert len(v1.ballots) == 67
    diop = next(b for b in v1.ballots if b.person_ref.raw == "Diop Paco")
    assert diop.choice == Choice.ei and diop.group_text == "VAS"
    assert [(m.kind, m.outcome, m.proposer_ref.raw) for m in item.motions] == [
        ("send_back", Outcome.rejected, "Diop"),
        ("counter_proposal", Outcome.rejected, "Koiranen"),
    ]


def test_item_without_history_or_vote():
    a = adapter()
    m = council_meeting(a)
    item = a.fetch_item(a.item_refs(m)[0])
    assert [s.type for s in item.sections] == ["proposal", "decision"]
    assert item.votes == [] and item.attachments == []


def test_agenda_items_have_no_pykala_or_votes():
    a = adapter()
    refs = a.list_meetings(COUNCIL, dt.date(2026, 11, 1), None)
    m = a.fetch_meeting(refs[-1])
    assert m.stage == Stage.agenda and m.attendance == []
    items = [a.fetch_item(r) for r in a.item_refs(m)]
    assert all(i.pykala is None and i.votes == [] for i in items)
    assert items[-1].sections[-1].type == "proposal"


def test_vote_pdf_layout():
    votes = tp.parse_vote_pdf((FIXTURES / "vote-2531451.pdf").read_bytes())
    assert [v.agenda_no for v in votes] == ["4", "4"]
    assert all(len(v.ballots) == 67 and not v.leftover for v in votes)
    assert votes[0].groups["Toivari Henry"] == "HT"
    line = "Eloranta Eeva-Johanna SDP J Uusitalo-Heikkinen Mervi VAS E"
    assert [(n, c) for n, c in tp.parse_vote_pdf_lines(["Äänestys / Omröstning 1", line])[0].ballots] == [
        ("Eloranta Eeva-Johanna", Choice.jaa),
        ("Uusitalo-Heikkinen Mervi", Choice.ei),
    ]


def test_prose_totals():
    lines = [
        "Suoritetussa koneäänestyksessä 50 valtuutettua kannatti kaupunginhallituksen ehdotusta ja "
        "15 valtuutettua kannatti Virtasen muutosehdotusta ja 2 valtuutettua äänesti tyhjää."
    ]
    assert [(p.a, p.b, p.tyhja) for p in tp.parse_prose(lines)] == [(50, 15, 2)]


def run(tmp_path, site=None):
    site = site or FakeTurku()
    (tmp_path / "config" / "bodies").mkdir(parents=True, exist_ok=True)
    report = crawl(TurkuAdapter(client(site), BASE), "turku", since=dt.date(2026, 10, 1), today=TODAY,
                   data_dir=tmp_path / "data", config_dir=tmp_path / "config")  # fmt: skip
    return report, site


def test_full_crawl_writes_meetings_and_validates(tmp_path):
    report, site = run(tmp_path)
    assert report.alarms == [] and report.parse_errors == 0
    data = tmp_path / "data"
    files = sorted(p.name for p in (data / "turku" / "meetings").rglob("*.json"))
    assert files == ["kaupunginvaltuusto--2026-10-26.json", "kaupunginvaltuusto--2026-11-16.json"]
    mf = jsonio.read(data / "turku" / "meetings" / "2026" / "kaupunginvaltuusto--2026-10-26.json")
    assert [len(i["votes"]) for i in mf["items"]] == [0, 0, 2, 0]
    r = validate_city("turku", data)
    assert r.ok, (r.errors, r.warnings)


def test_second_run_produces_no_diff(tmp_path):
    run(tmp_path)
    before = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    report, _ = run(tmp_path)
    assert report.files_changed == 0
    assert {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()} == before


# Layouts from the 2025 council vote lists (live crawl 2026-11-15): a name in lower case, a long name
# wrapped onto its own line, a wrapped item title on every page, and an absentee counted but unnamed.
OLDER_LIST = """Äänestyslista / Omröstningsförteckning — Kaupunginvaltuusto 17.3.2025 klo 18:00
Asia / Ärende 4 Asuinrakennusten tontin (II) myyminen tontinluovutuskilpailun
voittajalle, os. Luostarinkatu 5b
Äänestys / Omröstning 1
Jaa / Ja Ehdotus / Förslag Kh
Ei / Nej Muutos / Ändring Perho Anu (Anttila Juha)
Jaa / Ja 3
Ei / Nej 1
Tyhjää / Blankt 1
Poissa / Frånvarande 1
el-Khatib Amro VAS E Rantanen Elina VIHR J
Epse Samfoga Doh VIHR J Rosenlöf Jarmo SDP J
Theresia
Kossila Pauli JÄ T
Äänestyslista / Omröstningsförteckning — Kaupunginvaltuusto 17.3.2025 klo 18:00
Asia / Ärende 4 Asuinrakennusten tontin (II) myyminen tontinluovutuskilpailun
voittajalle, os. Luostarinkatu 5b
""".splitlines()


def test_older_vote_list_layouts():
    (v,) = tp.parse_vote_pdf_lines(OLDER_LIST)
    assert v.leftover == []
    assert [n for n, _ in v.ballots] == [
        "el-Khatib Amro", "Rantanen Elina", "Epse Samfoga Doh Theresia", "Rosenlöf Jarmo", "Kossila Pauli"
    ]  # fmt: skip
    assert v.groups["Epse Samfoga Doh Theresia"] == "VIHR" and v.groups["Kossila Pauli"] == "JÄ"
    prose = tp.parse_prose([
        "Suoritetussa koneäänestyksessä 3 valtuutettua kannatti kaupunginhallituksen ehdotusta ja 1 "
        "valtuutettu kannatti Perhon muutosehdotusta ja 1 valtuutettu äänesti tyhjää."
    ])  # fmt: skip
    assert [(p.a, p.b, p.tyhja) for p in prose] == [(3, 1, 1)]
    from kunta.adapters.turku import _drop_unlisted_absentees
    from kunta.parsers import votes_cloudmeeting as vc

    (ev,) = vc.build_votes(prose, [v], item_url="u", pdf_url="p")
    assert ev.needs_review and "poissa" in ev.review_reason
    _drop_unlisted_absentees(ev)
    assert not ev.needs_review, ev.review_reason


def test_prose_short_blank_form():
    s = (
        "Suoritetussa koneäänestyksessä 45 valtuutettua kannatti kaupunginhallituksen ehdotusta ja 20 "
        "valtuutettua kannatti Koirasen muutosehdotusta, 1 tyhjä ja 1 poissa, joten ehdotus hyväksyttiin."
    )
    assert [(p.a, p.b, p.tyhja) for p in tp.parse_prose([s])] == [(45, 20, 1)]


def test_validate_accepts_unnamed_absentees(tmp_path):
    report, _ = run(tmp_path)
    path = tmp_path / "data" / "turku" / "meetings" / "2026" / "kaupunginvaltuusto--2026-10-26.json"
    mf = jsonio.read(path)
    vote = mf["items"][2]["votes"][0]
    vote["counts"]["poissa"] = 1  # counted, but nobody named absent
    jsonio.write(path, mf)
    r = validate_city("turku", tmp_path / "data")
    assert r.warnings == [], r.warnings
