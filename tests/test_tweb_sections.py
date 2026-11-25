"""Tweb installs that serve UTF-16 HTML and an HTML "Läsnäolijat" cover (Hämeenlinna, 2026-11-20)."""

import datetime as dt
from pathlib import Path

from kunta.models import MotionKind, Outcome, SectionType
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


def test_raasepori_swedish_motions_and_votes():
    doc = item("raasepori_fullmaktige_2025-01-20_5.html")
    motions, prose = tp.parse_case(tp.item_sections(doc)[2])
    assert [(p.a, p.b, p.tyhja, p.jaa_label, p.ei_label) for p in prose] == [
        (9, 34, 0, "Remittering", "Fortsatt behandling"),
        (34, 6, 3, "Stadsstyrelsens förslag", "Orres förslag"),
    ]
    got = [(m.kind, m.proposer_ref.raw, [s.raw for s in m.seconder_refs], m.outcome) for m in motions]
    assert got == [
        (MotionKind.send_back, "Werner Orre", ["Mikael Borgman"], Outcome.rejected),
        (MotionKind.counter_proposal, "Werner Orre", ["Sven Holmberg", "Roger Hafström"], Outcome.rejected),
    ]


# -- covers in other layouts (2026-11-24) ---------------------------------------------------


def test_raasepori_swedish_section_cover():
    html = (FIXTURES / "raasepori_fm_2025-01-20_cover.html").read_text(encoding="utf-8")
    assert tp.is_section_cover(html)
    cover = tp.parse_cover_sections(html)
    assert (cover.date.isoformat(), cover.start_time, cover.end_time) == ("2025-01-20", "18:08", "19:27")
    assert cover.location == "Karjaan yhteiskoulu, Ekenäsvägen 62"  # under "{Sammanträdesplats}"
    got = {p.name: (p.role, p.present) for p in cover.participants}
    assert len(got) == 53
    assert got["Walls Anders"] == ("ordförande", True)
    assert got["Kajander Petri"] == ("I viceordförande", True)
    assert got["Ahomaa Petteri"] == ("jäsen", True)
    assert got["Hellén Roy"] == ("varajäsen", True)
    assert got["Alén Bella"] == ("jäsen", False)
    assert got["Theman Petra"] == ("stadsdirektör", True)
    assert sum(1 for p in cover.participants if p.present and p.role != "varajäsen") == 43


def test_ilmajoki_table_in_section():
    html = """<h1>Läsnäolijat</h1><h2>Aika</h2><p>12.12.2025 klo 18.00 - 19.30</p>
<h2>Päätöksentekijät</h2><p><table border="0"><tbody>
<tr><td>Niemistö Esa</td><td>puheenjohtaja</td></tr>
<tr><td>Pöytälaakso Niclas</td><td>I varapuheenjohtaja</td></tr>
<tr><td>Koski Matti</td><td></td></tr></tbody></table></p>
<h2>Poissa</h2><p>Aho Ville</p>"""
    cover = tp.parse_cover_sections(html)
    got = [(p.name, p.role, p.present) for p in cover.participants]
    assert got == [
        ("Niemistö Esa", "puheenjohtaja", True),
        ("Pöytälaakso Niclas", "I varapuheenjohtaja", True),
        ("Koski Matti", "jäsen", True),
        ("Aho Ville", "jäsen", False),
    ]


def test_rauma_osallistujat_pdf_cover():
    lines = (FIXTURES.parent / "tweb_pdf" / "rauma_kh_2025-01-20_cover.txt").read_text(encoding="utf-8")
    cover = tp.parse_cover(lines.splitlines())
    assert (cover.date.isoformat(), cover.start_time, cover.end_time) == ("2025-01-20", "15:30", "19:23")
    assert cover.location == "KH:n kokoushuone"
    got = {p.name: (p.role, p.present, p.note) for p in cover.participants}
    assert len(got) == 30
    assert got["Leppikorpi Kalle"] == ("puheenjohtaja", True, None)
    assert got["Vahteristo Samu"] == (
        "I varapuheenjohtaja",
        True,
        "poistui esteellisenä §:n 9 käsittelyn ajaksi",
    )
    assert got["Hiljanen Heidi"] == ("jäsen", True, None)  # the footnote column is not hers
    assert got["Kallio Reijo"] == ("KV:n I vpj", True, None)
    assert got["Hyvärinen Atte"] == ("teknisen toimialan vs. toimialajohtaja", False, None)
    assert got["Kumpula Olli-Pekka"] == ("tilapalvelujohtaja", True, "paikalla kokouksessa klo 17.24-17.45")


def _cover(body: str) -> list[tuple[str, str, bool, str | None]]:
    html = "<html><body><h1>Läsnäolijat</h1>" + body + "</body></html>"
    assert tp.is_section_cover(html)
    return [(p.name, p.role, p.present, p.note) for p in tp.parse_cover_sections(html).participants]


def test_kerava_party_first():
    got = _cover(
        "<h2>Aika</h2><p>9.11.2026 klo 18:00 - 20:00</p><h2>Osallistujat</h2>"
        "<p>(KOK) Enjala Terhi, puheenjohtaja<br>(KESK) Laaninen Timo, 2. varapuheenjohtaja<br>"
        "(VAS) Alam Shamsul, jäsen</p>"
    )
    assert got == [
        ("Enjala Terhi", "puheenjohtaja", True, None),
        ("Laaninen Timo", "2. varapuheenjohtaja", True, None),
        ("Alam Shamsul", "jäsen", True, None),
    ]


def test_nokia_bare_names_and_kuusamo_attachment():
    assert _cover("<h2>Jäsenet</h2><p>Aarne Jukka-Pekka<br>Ahvenvaara Johanna</p>") == [
        ("Aarne Jukka-Pekka", "jäsen", True, None),
        ("Ahvenvaara Johanna", "jäsen", True, None),
    ]
    assert _cover("<h2>Jäsenet</h2><p>Liite: Nimenhuutoluettelo</p>") == []


def test_muurame_brackets_tails_and_tabs():
    html = (
        "<html><body><h2>Kokousaika</h2><p>16.11.2026 kello 17:01</p>"
        "<h2>Osallistujat</h2><p>Lauri Leskinen (pj.)<br>Ville Väyrynen (2. vpj), poissa<br>"
        "Jani Kokko, poissa<br>Mikko Holmberg, varajäsen</p>"
        "<h2>Muut läsnäolijat</h2><p>Jarkko Määttänen\t\tkunnanjohtaja<br>"
        "Jukka Kaistinen\t\t\ttalousjohtaja, kello 17.19-18.34 § 97-98</p></body></html>"
    )
    cover = tp.parse_cover_sections(html)
    assert (cover.date.isoformat(), cover.start_time) == ("2026-11-16", "17:01")
    got = [(p.name, p.role, p.present) for p in cover.participants]
    assert got[:4] == [
        ("Lauri Leskinen", "pj.", True),
        ("Ville Väyrynen", "2. vpj", False),
        ("Jani Kokko", "jäsen", False),
        ("Mikko Holmberg", "varajäsen", True),
    ]
    assert got[4] == ("Jarkko Määttänen", "kunnanjohtaja", True)
    assert got[5][0] == "Jukka Kaistinen"


def test_kauhajoki_role_first_and_lists():
    got = _cover(
        "<h2>Saapuvilla olleet jäsenet</h2><p>Puheenjohtaja, Hautala Lasse<br>"
        "I varapuheenjohtaja, Kuusisto Jaana<br>Valtuutettu, Björkman Petri</p>"
        "<h2>Varavaltuutetut</h2><p>Kiukkonen Olli, Mäki Erkki, Soini Pekka</p>"
        "<h2>Poissa olleet</h2><p>Aho Ville</p>"
    )
    assert got == [
        ("Hautala Lasse", "puheenjohtaja", True, None),
        ("Kuusisto Jaana", "I varapuheenjohtaja", True, None),
        ("Björkman Petri", "valtuutettu", True, None),
        ("Kiukkonen Olli", "varajäsen", True, None),
        ("Mäki Erkki", "varajäsen", True, None),
        ("Soini Pekka", "varajäsen", True, None),
        ("Aho Ville", "jäsen", False, None),
    ]


def test_pirkkala_table_cells():
    got = _cover(
        "<h2>Läsnäolijat</h2><p><table><tr><td>Tolvanen Taru</td><td>puheenjohtaja</td><td>Poissa</td></tr>"
        "<tr><td>Ahtiainen Veli-Matti</td><td>17.12 alkaen (§ 117)</td></tr>"
        "<tr><td>Alanne Noora</td><td></td></tr></table></p>"
    )
    assert got == [
        ("Tolvanen Taru", "puheenjohtaja", False, None),
        ("Ahtiainen Veli-Matti", "jäsen", True, "17.12 alkaen (§ 117)"),
        ("Alanne Noora", "jäsen", True, None),
    ]


def test_lieto_osallistujat_row_is_the_cover():
    page = tp.parse_meeting(
        MEETING.replace(">Läsnäolijat<", ">Osallistujat -<"), "https://lieto-julkaisu.triplancloud.fi"
    )
    assert page.cover_pdf.endswith("docid=999307")


def _pdf_cover(name: str) -> tp.Cover:
    text = (FIXTURES.parent / "tweb_pdf" / f"{name}_cover.txt").read_text(encoding="utf-8")
    return tp.parse_cover(text.splitlines())


def test_akaa_block_cover():
    got = {p.name: (p.role, p.present, p.note) for p in _pdf_cover("akaa_kh_2026-11-17").participants}
    assert len(got) == 17
    assert got["Einola-Virtanen Heli"] == ("I varapuheenjohtaja", True, None)
    assert got["Piirainen Heli"] == ("varajäsen", True, "18.07-20.41")
    assert got["Ahola Sami"] == ("valtuuston I varapuheenjohtaja", True, "18.00-21.22, 21.23-21.37")
    assert got["Pulkkinen Mervi"] == ("II varapuheenjohtaja", False, None)
    assert got["Lohi Mika"] == ("jäsen", False, None)  # its role sits on the line above


def test_valkeakoski_block_cover_with_lists():
    cover = _pdf_cover("valkeakoski_kv_2026-11-16")
    assert (cover.date.isoformat(), cover.start_time, cover.end_time) == ("2026-11-16", "10:00", "12:21")
    got = {p.name: (p.role, p.present, p.note) for p in cover.participants}
    assert len(got) == 50
    assert got["Franssila Mikko"] == ("puheenjohtaja", True, None)
    assert got["Eerola-Nieminen Riikka-Leena"] == ("jäsen", True, None)  # wrapped across lines
    assert got["Järvinen Pekka"] == ("jäsen", True, "saapui klo. 11.48")
    assert got["Rautanen Ramona"] == ("varajäsen", True, "klo 10.00 – 11.48")
    assert got["Nyrhilä Aapeli"] == ("nuorisovaltuuston varaedustaja", True, "saapui klo. 11.33")
    assert got["Salminen Kari"] == ("jäsen", False, None)
    assert sum(1 for r, p, _ in got.values() if p and r in ("jäsen", "puheenjohtaja")) == 40


def test_lieto_table_cover():
    cover = _pdf_cover("lieto_kv_2026-11-16")
    assert (cover.start_time, cover.end_time) == ("17:30", "19:02")
    got = {p.name: (p.role, p.present) for p in cover.participants}
    assert got["Kolkkala Riina"] == ("puheenjohtaja", True)
    assert got["Kuokkanen Jukka-Pekka"] == ("III varapuheenjohtaja", True)
    assert got["Ala-Nissilä Simo"] == ("jäsen", True)
    assert got["Ruuskanen Päivi"] == ("varajäsen", True)
    assert got["Esimerkki Erkki"] == ("kaupunginjohtaja", True)
    assert len(got) == 9  # the repeated page header is not a person


# -- votes and motions in other layouts (2026-11-25) ----------------------------------------


def _case(name: str) -> tuple[list[tp.ItemDoc], list, list]:
    lines = (FIXTURES.parent / "tweb_pdf" / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    doc = tp.parse_item_lines(lines, lines[0])
    sections, _, deliberation = tp.item_sections(doc)
    motions, prose = tp.parse_case(deliberation)
    return sections, motions, prose


def test_rauma_inline_headings_and_named_sides():
    sections, motions, prose = _case("rauma_kv_2026-10-26_74")
    assert [(s.type, s.heading) for s in sections][1:] == [
        (SectionType.proposal, "Päätösehdotus"),
        (SectionType.deliberation, "Kokouskäsittely"),
        (SectionType.decision, "Päätös"),
    ]
    assert sections[0].heading == "Kaupunginhallitus 5.10.2026 § 290"  # "273 § 22.6.2026" order
    assert sections[-1].text == "Hyväksyttiin."
    assert "RAUMAN KAUPUNKI" not in sections[2].text  # the running page header is dropped
    [mo] = motions
    assert (mo.kind, mo.proposer_ref.raw, mo.outcome) == (
        MotionKind.send_back,
        "Leppikorpi",
        Outcome.rejected,
    )
    assert [s.raw for s in mo.seconder_refs] == ["Virtasen"]
    [pv] = prose
    assert (pv.a, pv.b, pv.tyhja) == (25, 18, 0)
    assert pv.jaa_label == "asian asiallisen käsittelyn jatkaminen"


def test_rauma_sai_first_and_dash_rule():
    sections, motions, prose = _case("rauma_kv_2026-08-31_46")
    assert sections[0].type == SectionType.history
    [mo] = motions
    assert (mo.proposer_ref.raw, mo.outcome) == ("Toivonen", Outcome.rejected)
    [pv] = prose
    assert (pv.a, pv.b) == (37, 6)
    assert pv.ei_label.startswith("Toivosen ym. ehdottama")


def test_kangasala_prose_without_kasittely_heading():
    sections, motions, prose = _case("kangasala_kv_2026-11-09_75")
    assert sections[0].heading == "Kaupunginhallitus 2.11.2026 § 300"  # "Valtuusto …" is its own block
    [mo] = motions
    assert (mo.proposer_ref.raw, mo.outcome) == ("Marika Uusi-Illikainen", Outcome.rejected)
    [pv] = prose
    assert (pv.a, pv.b) == (36, 15)
    assert pv.jaa_label == "kaupunginhallituksen esitys"


def test_pirkkala_jaa_ei_blocks():
    lines = (FIXTURES.parent / "tweb_pdf" / "pirkkala_kv_2026-11-16_120.txt").read_text(encoding="utf-8")
    motions, prose = tp.parse_case(lines.splitlines())
    assert [(p.a, p.b, p.jaa_label, p.ei_label) for p in prose] == [
        (34, 9, "Kh - pohjaehdotus", "Palinin ehdotus"),
        (29, 14, "asian käsittelyä jatketaan", "palautetaan"),
    ]
    assert [(m.kind, m.proposer_ref.raw, m.outcome) for m in motions] == [
        (MotionKind.counter_proposal, "Henna Palini", Outcome.rejected),
        (MotionKind.send_back, "Hietalahde", Outcome.rejected),
    ]


def test_nominative_and_page_header():
    assert tp._nominative("Raili Naskalin") == "Raili Naskali"
    assert tp._nominative("Veli-Matti Ahtiaisen") == "Veli-Matti Ahtiainen"
    doc = tp.parse_item_lines(
        [
            "Asia",
            "Valtuusto 11.5.2026 § 33",
            "Ne, jotka kannattavat asian",
            "Kangasalan kaupunki",
            "______________",
            "palauttamista, äänestävät ei.",
        ],
        "Asia",
    )
    assert tp._flat(doc.blocks[0].lines) == "Ne, jotka kannattavat asian palauttamista, äänestävät ei."
