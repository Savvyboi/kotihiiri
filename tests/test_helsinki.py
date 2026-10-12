import datetime as dt
from pathlib import Path

import pytest

from kunta import jsonio
from kunta.adapters.base import TransientItemError
from kunta.adapters.helsinki import HelsinkiAdapter, build_item
from kunta.models import Body, ItemRef, MeetingRef, Stage
from kunta.parsers import helsinki as hp
from kunta.text import contains_pii
from tests.helsinki_site import FIXTURES, FakeHelsinki, client

GOLDEN = Path(__file__).resolve().parent / "golden" / "helsinki"
COUNCIL = Body(
    id="helsinki/kaupunginvaltuusto",
    city="helsinki",
    name_fi="Kaupunginvaltuusto",
    kind="council",
    source_ids={"slug": "kaupunginvaltuusto"},
)
VOTE_URL = "https://paatokset.hel.fi/fi/asia/hel-2026-008342?paatos=6c1e0a7d-0000-4000-8000-000000000001"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def vote_item(stage=Stage.minutes):
    ref = ItemRef(meeting_id="helsinki/kaupunginvaltuusto/2026-09-23", ordinal=13, source_url=VOTE_URL,
                  stage=stage, title="Länsisataman pikaraitiotien hankesuunnitelma", pykala=261)  # fmt: skip
    return build_item(ref, hp.parse_item(fixture("item-hel-2026-008342.html")))


def test_discover_bodies_applies_exclude_rules():
    adapter = HelsinkiAdapter(client(FakeHelsinki()))
    bodies = {b.id.split("/")[1]: b for b in adapter.discover_bodies()}
    for seed in ("kaupunginvaltuusto", "kaupunginhallitus", "kaupunginhallituksen-konsernijaosto",
                 "kaupunginhallituksen-elinkeinojaosto"):  # fmt: skip
        assert bodies[seed].included
    for excluded in ("kaupunkiymparistolautakunnan-ymparisto-ja-lupajaosto", "keskusvaalilautakunta",
                     "sosiaali-terveys-ja-pelastuslautakunnan-yksiloasioiden-jaosto"):  # fmt: skip
        assert not bodies[excluded].included
    assert "viranhaltijat" not in bodies and "lautakunnat-ja-johtokunnat" not in bodies
    assert bodies["kaupunginvaltuusto"].kind == "council"
    assert bodies["kaupunginhallitus"].kind == "board"
    assert bodies["kaupunginhallituksen-konsernijaosto"].kind == "section"
    assert bodies["liikenneliikelaitoksen-johtokunta"].kind == "enterprise_board"
    assert bodies["tarkastuslautakunta"].kind == "committee"


def test_list_meetings_paginates_until_since():
    site = FakeHelsinki()
    adapter = HelsinkiAdapter(client(site))
    refs = adapter.list_meetings(COUNCIL, dt.date(2025, 1, 1), None)
    assert [r.date.isoformat() for r in refs] == ["2025-01-15", "2026-09-09", "2026-09-23", "2026-10-07"]
    assert [r.stage for r in refs] == ["minutes", "minutes", "agenda", "agenda"]
    assert refs[0].source_ids == {"meeting_code": "0290020251", "number": "1/2025"}
    assert all("#" not in r.source_url for r in refs)
    listing = [u for u in site.requests if "/asiakirjat?" in u]
    assert listing == ["/fi/paattajat/kaupunginvaltuusto/asiakirjat?page=0",
                       "/fi/paattajat/kaupunginvaltuusto/asiakirjat?page=1"]  # fmt: skip
    assert [r.date for r in adapter.list_meetings(COUNCIL, dt.date(2026, 9, 1), dt.date(2026, 9, 30))] == [
        dt.date(2026, 9, 9),
        dt.date(2026, 9, 23),
    ]


def test_same_day_meetings_get_suffix():
    html = fixture("listing-kaupunginvaltuusto-0.html").replace("Päätöksentekopäivä: 9.9.2026",
                                                                 "Päätöksentekopäivä: 23.9.2026")  # fmt: skip
    rows = hp.parse_listing(html, "kaupunginvaltuusto")
    assert [r.date for r in rows].count(dt.date(2026, 9, 23)) == 2
    site = FakeHelsinki()
    site.overrides["/fi/paattajat/kaupunginvaltuusto/asiakirjat"] = "listing-kaupunginvaltuusto-0.html"
    adapter = HelsinkiAdapter(client(site))
    adapter._get = lambda p: html if "asiakirjat?page=0" in p else "<main></main>"  # type: ignore[method-assign]
    refs = adapter.list_meetings(COUNCIL, dt.date(2026, 1, 1), None)
    assert [(r.date.isoformat(), r.same_day_index) for r in refs] == [
        ("2026-09-23", 1), ("2026-09-23", 2), ("2026-10-07", 1)]  # fmt: skip


def test_minutes_meeting_page():
    page = hp.parse_meeting(fixture("meeting-02900202614.html"))
    assert page.stage == Stage.minutes
    assert page.date == dt.date(2026, 9, 23)
    assert page.start_time == "18:00"
    assert page.location == "Valtuustosali, Aleksanterinkatu 20"
    assert [(r.ordinal, r.pykala) for r in page.rows] == [(1, 249), (2, 250), (13, 261)]
    assert page.rows[2].url == VOTE_URL
    assert page.print_pdf.startswith("https://ahjojulkaisu.hel.fi/")
    assert page.transcript_pdf.endswith("14_kvsto_23092026.pdf")
    assert "icareus.com" in page.video_url


def test_agenda_with_decision_bulletin_is_decisions_stage():
    page = hp.parse_meeting(fixture("meeting-02900202615.html"))
    assert page.stage == Stage.decisions
    assert [(r.ordinal, r.pykala) for r in page.rows] == [(1, None), (2, None), (3, None)]


def test_fetch_meeting_builds_ids_and_item_refs():
    adapter = HelsinkiAdapter(client(FakeHelsinki()))
    ref = MeetingRef(body_id=COUNCIL.id, date=dt.date(2026, 9, 23), stage="agenda",
                     source_url="https://paatokset.hel.fi/fi/paattajat/kaupunginvaltuusto/asiakirjat/02900202614",
                     source_ids={"meeting_code": "02900202614"})  # fmt: skip
    m = adapter.fetch_meeting(ref)
    assert m.id == "helsinki/kaupunginvaltuusto/2026-09-23"
    assert m.stage == "minutes"  # the page is newer than the listing label
    assert m.items == [f"{m.id}/1", f"{m.id}/2", f"{m.id}/13"]
    assert m.minutes_pdf_url and m.source_ids["transcript_pdf"]
    refs = adapter.item_refs(m)
    assert refs[2].source_ids == {
        "case": "hel-2026-008342",
        "decision": "6c1e0a7d-0000-4000-8000-000000000001",
    }
    assert refs[0].source_ids == {"case": "26ac134e-452f-43dd-a7e2-42600821c38e"}


def test_council_vote_with_groups_and_history_votes_ignored():
    item = vote_item()
    assert len(item.votes) == 1  # the board's and committee's votes in Päätöshistoria are not attached
    v = item.votes[0]
    assert (v.counts.jaa, v.counts.ei, v.counts.tyhja, v.counts.poissa) == (34, 36, 15, 0)
    assert len(v.ballots) == 85 and all(b.group_text for b in v.ballots)
    assert not v.needs_review
    assert v.jaa_label.startswith("Valtuutettu Otso Kivekkään")
    assert v.ei_label == "Vastustaa"
    assert v.result_text.startswith("Kaupunginvaltuusto ei hyväksynyt")
    assert v.source == "html" and v.source_url == VOTE_URL


def test_item_sections_motions_and_metadata():
    item = vote_item()
    assert item.pykala == 261 and item.case_number == "HEL 2026-008342"
    assert item.presenter == "Kaupunginhallitus"
    types = [s.type for s in item.sections]
    assert types == ["decision", "deliberation", "proposal", "background", "history", "history"]
    assert [s.heading for s in item.sections if s.type == "history"] == [
        "Kaupunginhallitus 07.09.2026 § 609", "Kaupunkiympäristölautakunta 18.08.2026 § 402"]  # fmt: skip
    every_text = " ".join(s.text for s in item.sections)
    assert "Kunnallisvalitus" not in every_text  # Muutoksenhaku dropped
    assert "Anna Esimerkki" not in every_text  # Lisätietojen antaja dropped
    assert "Äänestystulos valtuustoryhmittäin" not in every_text
    assert not any(contains_pii(s.text) for s in item.sections)
    assert len(item.attachments) == 3
    (motion,) = item.motions
    assert motion.kind == "resolution"
    assert motion.proposer_ref.raw == "Otso Kivekäs"
    assert [s.raw for s in motion.seconder_refs] == ["Silvia Modig"]
    assert motion.outcome == "rejected"


def test_agenda_stage_item_has_no_votes():
    item = vote_item(stage=Stage.agenda)
    assert item.votes == [] and item.motions == []


def test_ids_and_hash_stable_across_parses():
    a, b = vote_item(), vote_item()
    assert jsonio.dumps(a) == jsonio.dumps(b)


def test_load_error_is_transient_at_minutes_stage():
    site = FakeHelsinki()
    site.overrides["/fi/asia/x"] = "item-load-error.html"
    adapter = HelsinkiAdapter(client(site))
    ref = ItemRef(meeting_id="helsinki/kaupunginvaltuusto/2026-09-23", ordinal=1,
                  source_url="https://paatokset.hel.fi/fi/asia/x")  # fmt: skip
    with pytest.raises(TransientItemError):
        adapter.fetch_item(ref)
    ok = adapter.fetch_item(ref.model_copy(update={"source_url": "https://paatokset.hel.fi/fi/asia/y"}))
    assert ok.sections[0].type == "decision"


def test_golden_vote_item(request):
    path = GOLDEN / "item-hel-2026-008342.json"
    data = jsonio.dumps(vote_item())
    if request.config.getoption("--update-goldens"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    assert path.read_bytes() == data


def parsed(name: str, stage=Stage.minutes):
    ref = ItemRef(meeting_id="helsinki/x/2025-01-14", ordinal=4, source_url="https://paatokset.hel.fi/fi/asia/y",
                  stage=stage)  # fmt: skip
    return build_item(ref, hp.parse_item(fixture(name)))


def test_forwarded_matter_esitys_is_the_decision():
    item = parsed("item-forwarded.html")
    assert [s.type for s in item.sections] == ["decision", "deliberation", "proposal", "background"]
    assert item.sections[0].text == "Kaupunkiympäristölautakunta päätti panna asian pöydälle."
    assert "40 % on luontoalueita" in item.sections[3].text
    assert "KASKO-01-1029-25" in item.sections[3].text  # a case code, not a phone number
    assert item.presenter == "Ville Lehmuskoski, Kaupunkiympäristön toimialajohtaja"
    every = " ".join(s.text for s in item.sections) + (item.presenter or "")
    assert "Etu Suku" not in every and not contains_pii(every)
    assert len(item.attachments) == 1


def test_swedish_section_headings():
    item = parsed("item-swedish.html")
    assert [s.type for s in item.sections] == ["decision", "proposal", "background"]
    assert item.presenter == "Niclas Grönholm, Direktör för den svenska servicehelheten"
    assert not any("missnöjd" in s.text for s in item.sections)


def test_page_with_content_is_not_transient_despite_hidden_error_markup():
    site = FakeHelsinki()
    site.overrides["/fi/asia/x"] = "item-forwarded.html"
    adapter = HelsinkiAdapter(client(site))
    ref = ItemRef(
        meeting_id="helsinki/x/2025-01-14", ordinal=4, source_url="https://paatokset.hel.fi/fi/asia/x"
    )
    assert adapter.fetch_item(ref).sections[0].type == "decision"


def test_confidential_item_is_final_not_transient():
    site = FakeHelsinki()
    site.overrides["/fi/asia/x"] = "item-load-error.html"
    adapter = HelsinkiAdapter(client(site))
    ref = ItemRef(
        meeting_id="helsinki/x/2025-01-14",
        ordinal=24,
        title="Salassa pidettävä (JulkL (621/1999) 24.1 § 25 k)",
        source_url="https://paatokset.hel.fi/fi/asia/x",
    )
    assert adapter.fetch_item(ref).sections == []
