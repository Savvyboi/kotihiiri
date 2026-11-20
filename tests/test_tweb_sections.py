"""Tweb installs that serve UTF-16 HTML and an HTML "Läsnäolijat" cover (Hämeenlinna, 2026-11-20)."""

import datetime as dt
from pathlib import Path

from kunta.models import Outcome, SectionType
from kunta.parsers import tweb as tp
from kunta.parsers.votes_cloudmeeting import VOTE_LIST_TITLE

COVER = """<html><body><h1>Kaupunginvaltuusto</h1>
<h2>Aika</h2><p>9.6.2025 18:00 - 20:27</p>
<h2>Paikka</h2><p>Raatihuone, valtuustosali</p>
<h2>Kokouksen asiat</h2><p>§:t 72-101</p>
<h2>Päätöksentekijät</h2><p>Aaltonen Satu<br />Lehtonen Terhi § 72-86 klo 18.00-19.02<br />
Keränen Anne-Mari (kokoomuksen 1. varavaltuutettu)<br />
Taavela Irma (sosialidemokraattien 1. varavaltuutettu) § 86-101 klo 19.02-20.27<br />
Lehto Kirsi, 1. varapuheenjohtaja</p>
<h2>Muut osallistujat</h2><p>Parviainen Olli-Poika, kaupunginjohtaja<br />
Oksa Jussi, talousjohtaja § 86-92 klo 13.07-13.32</p>
<h2>Poissa</h2><p>Rantanen Emmi<br />Silpola Veli-Antti</p>
<h2>Puheenjohtaja</h2><p>Juha Tuomi § 72-76<br />Jari Koskinen § 77-101</p>
</body></html>"""

MEETING = """<html><body><table>
<tr><td></td><td><a href="/ktwebscr/fileshow?doctype=7&docid=999307">Läsnäolijat</a>&nbsp;
<a href="/ktwebscr/fileshow?doctype=3&docid=999307">(PDF)</a></td></tr>
<tr><td>72</td><td><a href="/ktwebscr/fileshow?doctype=3&docid=999310">Nimenhuuto</a></td><td></td></tr>
<tr><td></td><td><a href="/ktwebscr/fileshow?doctype=3&docid=999299">Kunnallisvalitus, KV</a></td></tr>
</table></body></html>"""


def test_utf16_without_bom_decodes():
    assert tp.decode(COVER.encode("utf-16-le")) == COVER
    assert tp.decode(COVER.encode("utf-16")) == COVER
    assert tp.decode("Läsnä".encode()) == "Läsnä"
    assert tp.decode("Läsnä".encode("cp1252")) == "Läsnä"


def test_utf16_item_gives_lines():
    lines = tp.html_lines(
        tp.decode("<html><body><p>Päätös</p><p>Hyväksyttiin.</p></body></html>".encode("utf-16-le"))
    )
    assert lines == ["Päätös", "Hyväksyttiin."]


def test_lasnaolijat_row_is_the_cover():
    page = tp.parse_meeting(MEETING, "https://hameenlinna.tweb.fi")
    assert page.cover_pdf == "https://hameenlinna.tweb.fi/ktwebscr/fileshow?doctype=7&docid=999307"
    assert [r.pykala for r in page.rows] == [72]


def test_section_cover():
    assert tp.is_section_cover(COVER)
    cover = tp.parse_cover_sections(COVER)
    assert (cover.date.isoformat(), cover.start_time, cover.end_time) == ("2025-06-09", "18:00", "20:27")
    assert cover.location == "Raatihuone, valtuustosali"
    got = {p.name: (p.role, p.present, p.note) for p in cover.participants}
    assert len(got) == 9  # the chair and the minute-taker are not attendance
    assert got["Aaltonen Satu"] == ("jäsen", True, None)
    assert got["Lehtonen Terhi"] == ("jäsen", True, "§ 72-86 klo 18.00-19.02")
    assert got["Taavela Irma"] == (
        "sosialidemokraattien 1. varavaltuutettu",
        True,
        "§ 86-101 klo 19.02-20.27",
    )
    assert got["Lehto Kirsi"] == ("1. varapuheenjohtaja", True, None)
    assert got["Oksa Jussi"] == ("talousjohtaja", True, "§ 86-92 klo 13.07-13.32")
    assert got["Silpola Veli-Antti"] == ("jäsen", False, None)


# -- items served as HTML (<header> + <h2> parts) -------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "tweb_html"


def item(name: str) -> tp.ItemDoc:
    raw = (FIXTURES / name).read_text(encoding="utf-8").encode("utf-16-le")  # as served
    html = tp.decode(raw)
    assert tp.is_html_item(html)
    return tp.parse_item_html(html)


def kinds(doc: tp.ItemDoc) -> list[tuple[SectionType, str | None]]:
    return [(s.type, s.heading) for s in tp.item_sections(doc)[0]]


def test_hameenlinna_item_own_handling_first_earlier_after():
    doc = item("hml_kv_2025-02-17_11.html")
    assert doc.case_number == "HML/550/00.01.01/2025"
    assert [b.header for b in doc.blocks] == [
        "Kaupunginhallitus 3.2.2025 § 32",
        "Kaupunginvaltuusto 17.2.2025 § 11",
    ]
    tp.end_at_meeting(doc, dt.date(2025, 2, 17), 11)
    assert kinds(doc) == [
        (SectionType.history, "Kaupunginhallitus 3.2.2025 § 32"),
        (SectionType.decision, "Päätös"),
        (SectionType.proposal, "Päätösehdotus"),
        (SectionType.deliberation, "Käsittely"),
    ]
    assert doc.attachment_titles[0] == "Äänestykset 11 § 17.2.2025 KV"
    assert VOTE_LIST_TITLE.search(doc.attachment_titles[0])


def test_hameenlinna_votes_and_motions():
    doc = item("hml_kv_2025-02-17_11.html")
    motions, prose = tp.parse_case(tp.item_sections(doc)[2])
    assert [(p.a, p.b, p.tyhja) for p in prose] == [(36, 13, 2), (41, 10, 0), (44, 7, 0), (37, 12, 2)]
    assert [p.ei_label for p in prose] == [
        "Laitisen muutosehdotus",
        "Frankin muutosehdotus",
        "Frankin muutosehdotus",
        "Reiman muutosehdotus",
    ]
    assert [m.proposer_ref.raw for m in motions] == [
        "Tiera Laitinen",
        "Karoliina Frank",
        "Karoliina Frank",
        "Aapo Reima",
    ]
    assert all(m.outcome == Outcome.rejected for m in motions)


def test_hameenlinna_short_item():
    doc = item("hml_kv_2025-06-09_72.html")
    assert kinds(doc) == [
        (SectionType.background, None),
        (SectionType.decision, "Päätös"),
        (SectionType.proposal, "Päätösehdotus"),
    ]


def test_kerava_item_list_stays_in_its_part():
    doc = item("kerava_kh_2025-01-13_2.html")
    assert [b.header for b in doc.blocks] == [
        "Kaupunginhallitus 13.1.2025 § 2"
    ]  # the repeated line is skipped
    sections = tp.item_sections(doc)[0]
    assert [s.type for s in sections] == [SectionType.background, SectionType.proposal, SectionType.decision]
    assert sections[2].text.endswith("strategiapäällikkö Emmi Kolis")


def test_raasepori_swedish_item():
    doc = item("raasepori_fullmaktige_2025-01-20_5.html")
    assert doc.case_number == "RBG/1303/01.01.01.01/2024"
    assert [b.header for b in doc.blocks] == ["Stadsstyrelsen 13.1.2025 § 6", "Fullmäktige 20.1.2025 § 5"]
    assert [t for t, _ in kinds(doc)] == [
        SectionType.background,
        SectionType.history,
        SectionType.proposal,
        SectionType.deliberation,
        SectionType.decision,
    ]
    empty = item("raasepori_fm_2025-01-20_1.html")  # "{Ärendenummer}:" with nothing under it
    assert empty.case_number is None
    assert [t for t, _ in kinds(empty)] == [SectionType.proposal, SectionType.decision]
