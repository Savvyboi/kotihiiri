"""Tweb installs that serve UTF-16 HTML and an HTML "Läsnäolijat" cover (Hämeenlinna, 2026-11-20)."""

from kunta.parsers import tweb as tp

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
