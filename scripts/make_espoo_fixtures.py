"""Generate reconstructed espoo.oncloudos.com fixtures in tests/fixtures/espoo (deterministic).

The cloud environment that built M2 could not reach espoo.oncloudos.com, so these pages are
rebuilt from the structure inspected by hand on 2026-10-13 (PLAN.md §16 S10): table headers, link
shapes, heading lines, prose sentences and the two Cloudmeeting vote-PDF layouts. Text is
shortened and member names are fictional; counts follow the real items (council 21.9.2026 § 132:
Jaa 30 / Ei 41 / Tyhjä 4; council 8.12.2025 § 167: six votes). Listing pages are written in
ISO-8859-1 like the real ones; item pages in UTF-8.

Needs reportlab for the PDFs (not a project dependency): `pip install reportlab`.
"""

from __future__ import annotations

import html
import io
import itertools
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "espoo"
CGI = "https://espoo.oncloudos.com/cgi/DREQUEST.PHP"
KOKOUS = "https://espoo.oncloudos.com/kokous"

FIRST = ["Aino", "Eero", "Helmi", "Ilmari", "Kerttu", "Lauri", "Mikko", "Noora", "Oona", "Pekka",
         "Riikka", "Sami", "Tuula", "Veikko", "Wilma", "Aleksi", "Elina", "Jouni J.", "Eva-Lena"]  # fmt: skip
LAST = ["Esimerkki", "Kuvitteellinen", "Mallinen", "Testaaja", "Harjoitus", "Näyte", "Malli",
        "Kokeilu", "Luonnos", "Demonen", "af Testsson", "Keksitty-Sipilä"]  # fmt: skip
NAMES = [f"{s} {f}" for s, f in itertools.islice(itertools.product(LAST, FIRST), 0, None, 3)][:75]
DEPUTY = "Varamies Ville"  # sits in for NAMES[0] in the 2025 budget votes

BODIES = [  # (dynasty id, name, latest meeting id, label, date)
    ("46164", "Kasvun ja oppimisen lautakunnan nuorisoasiainjaosto", "20251441", "Pöytäkirja", "15.05.2025"),
    ("46162", "Kasvun ja oppimisen lautakunta", "20261719", "Esityslista", "07.10.2026"),
    ("2243", "Kaupunginhallituksen elinkeino- ja kilpailukykyjaosto", "20261724", "Pöytäkirja", "05.10.2026"),
    ("164724", "Kaupunginhallituksen konserni- ja tilajaosto", "20261746", "Esityslista", "12.10.2026"),
    ("616", "Kaupunginhallituksen konsernijaosto", "20251444", "Pöytäkirja", "19.05.2025"),
    ("617", "Kaupunginhallituksen tila- ja asuntojaosto", "20251447", "Pöytäkirja", "26.05.2025"),
    (
        "165188",
        "Kaupunginhallituksen työllisyys- ja kotoutumisjaosto",
        "20261721",
        "Pöytäkirja",
        "21.09.2026",
    ),
    ("152830", "Kaupunginhallituksen työllisyysjaosto", "20251440", "Pöytäkirja", "19.05.2025"),
    ("182", "Kaupunginhallitus", "20261736", "Pöytäkirja", "05.10.2026"),
    ("162", "Kaupunkisuunnittelulautakunta", "20261740", "Esityslista", "14.10.2026"),
    ("2028", "Keskusvaalilautakunta", "20261728", "Esityslista", "06.10.2026"),
    ("164718", "Kulttuuri- ja nuorisolautakunta", "20261720", "Pöytäkirja", "15.09.2026"),
    ("161", "Kulttuurilautakunta", "20251458", "Pöytäkirja", "03.06.2025"),
    ("164720", "Liikunta- ja hyvinvointilautakunta", "20261699", "Pöytäkirja", "24.09.2026"),
    ("46112", "Liikuntalautakunta", "20251443", "Pöytäkirja", "05.06.2025"),
    ("890", "Nämnden Svenska rum", "20261711", "Pöytäkirja", "24.09.2026"),
    ("2029", "Tarkastuslautakunta", "20261748", "Esityslista", "07.10.2026"),
    ("160", "Tekninen lautakunta", "20261727", "Pöytäkirja", "23.09.2026"),
    (None, "Testitoimielin", None, "Ei julkaistuja kokouksia", ""),
    ("1", "Valtuusto", "20261743", "Esityslista", "19.10.2026"),
    ("46088", "Ympäristö- ja rakennuslautakunta", "20261734", "Pöytäkirja", "08.10.2026"),
]

CHROME_TOP = """
<div id="header"><a href="#maincontent">Siirry suoraan pääsisältöön</a>
<span>Espoon kaupunki</span> <a href="#">RSS</a> <a href="#">Haku</a></div>
<div id="search"><h2>Hae kokousasioista</h2>
<table><tr><td>Toimielin</td><td>Hakusanat</td></tr>
<tr><td><select><option>Kaikki</option></select></td><td><input type="text"></td></tr></table></div>
<ul class="breadcrumb"><li><a href="https://www.espoo.fi/">Espoon kaupunki</a></li>
<li><a href="{cgi}?page=meeting_handlers&amp;id=">Toimielimet</a></li><li>{crumb}</li></ul>
"""


def page(title: str, crumb: str, main: str, charset: str = "utf-8") -> str:
    return (
        '<!DOCTYPE html>\n<html lang="fi"><head>'
        f'<meta http-equiv="Content-Type" content="text/html; charset={charset}">'
        f"<title>{html.escape(title)} | Dynasty tietopalvelu : Espoon kaupunki</title></head>\n<body>"
        + CHROME_TOP.format(cgi=CGI, crumb=html.escape(crumb))
        + f'<div id="maincontent">\n{main}\n</div></body></html>\n'
    )


def write(name: str, text: str, encoding: str = "utf-8") -> None:
    (OUT / name).write_bytes(text.encode(encoding))


# -- listing pages (ISO-8859-1) -----------------------------------------------------------


def meeting_frames() -> str:
    rows = []
    for dyn, name, mid, label, date in BODIES:
        if dyn is None:
            rows.append(f"<tr><td>{name}</td><td>{label}</td><td></td></tr>")
            continue
        rows.append(
            f'<tr><td><a href="{CGI}?page=meetings&amp;id={dyn}">{html.escape(name)}</a></td>'
            f'<td><a href="{CGI}?page=meeting&amp;id={mid}">{label}</a></td><td>{date}</td></tr>'
        )
    main = (
        '<h1>Toimielimet</h1>\n<table class="list">\n'
        "<tr><th>Toimielin</th><th>Viimeisin kokous</th><th>Kokouspäivämäärä</th></tr>\n"
        + "\n".join(rows)
        + "\n</table>"
    )
    return page("Toimielimet", "Toimielimet", main, "iso-8859-1")


def meetings(name: str, years: dict[str, list[tuple[str, str, str]]]) -> str:
    parts = [f"<h1>{html.escape(name)}</h1>"]
    for year, rows in years.items():
        parts.append(f"<p><i>Vuosi {year}</i></p>")
        parts.append("<table><tr><th>Kokouspäivämäärä</th><th>Asiakirjatyyppi</th></tr>")
        for date, label, mid in rows:
            parts.append(
                f'<tr><td>{date}</td><td><a href="{CGI}?page=meeting&amp;id={mid}">{label}</a></td></tr>'
            )
        parts.append("</table>")
    return page(name, name, "\n".join(parts), "iso-8859-1")


# -- meeting pages ------------------------------------------------------------------------


def meeting(mid: str, h1: str, published: str, label: str, rows: list[tuple[int, int, str, bool]],
            participants: list[tuple[str, str]]) -> str:  # fmt: skip
    items = "\n".join(
        f"<tr><td>{pyk}</td><td>"
        + (
            '<img src="https://espoo.oncloudos.com/kuvat/icon_attachment2.png" alt="Sisältää liitteitä">'
            if att
            else ""
        )
        + f'</td><td><a href="{CGI}?page=meetingitem&amp;id={mid}-{n}">{html.escape(title)}</a></td></tr>'
        for n, pyk, title, att in rows
    )
    people = "\n".join(
        f"<tr><td>{html.escape(n)}</td><td>{html.escape(r)}</td></tr>" for n, r in participants
    )
    main = f"""<h1>{html.escape(h1)}</h1>
<p><b>Julkaistu:</b> {published}</p>
<p><a href="{KOKOUS}/{mid}.PDF">{label}</a> (pdf 1.19 mb)</p>
<p><i>Kokousasiat</i></p>
<table><tr><th>Pykälä</th><th>Liitteet</th><th>Otsikko</th></tr>
{items}
</table>
<p><i>Osallistujat</i></p>
<table><tr><th>Osallistuja</th><th>Tehtävä</th></tr>
{people}
</table>
<p><i>Nähtävilläolo</i></p>
<table><tr><th>Paikka</th><th>Alkaen</th></tr>
<tr><td>Tämä pöytäkirja on julkaistu yleisessä tietoverkossa</td><td>{published}</td></tr></table>"""
    return page(h1, "Kokous", main)


def council_participants() -> list[tuple[str, str]]:
    return ([(NAMES[1], "puheenjohtaja")] + [(n, "valtuutettu") for n in NAMES[2:]]
            + [("Nuorinen Nelli", "nuorisovaltuuston edustaja"), ("Johtaja Juhani", "kaupunginjohtaja"),
               ("Sihteeri Sanna", "kaupunginsihteeri, sihteeri")])  # fmt: skip


# -- item pages ---------------------------------------------------------------------------


def nav(mid: str, n: int) -> str:
    return (
        f'<table class="nav"><tr><td><a href="{CGI}?page=meetingitem&amp;id={mid}-{n - 1}">Edellinen asia</a> | '
        f'<a href="{CGI}?page=meetingitem&amp;id={mid}-{n + 1}">Seuraava asia</a></td>'
        f'<td><a href="{KOKOUS}/{mid}-{n}-0.PDF">Muutoksenhakuohje</a> (pdf 41.90 kb) '
        f'<a href="{KOKOUS}/{mid}-{n}.PDF">Kokousasia</a> (pdf 283.31 kb)</td></tr></table>'
    )


def heading(text: str, style: str) -> str:
    # Dynasty item text is converted from a word processor: some headings are heading tags,
    # others bold paragraphs. Both occur in the fixtures.
    return f"<h3>{text}</h3>" if style == "h" else f'<p class="Otsikko"><b>{text}</b></p>'


def item(h1: str, mid: str, n: int, body_line: str, pykala: int, title: str, sections: str,
         attachments: list[tuple[str, str]] = (), supplementary: list[tuple[str, str]] = ()) -> str:  # fmt: skip
    att_rows = "".join(
        f'<tr><td>{i}</td><td><a href="{url}">{html.escape(t)}</a> (pdf 92.52 kb)</td></tr>'
        for i, (t, url) in enumerate(attachments, start=1)
    )
    sup_rows = "".join(
        f'<tr><td><a href="{url}">{html.escape(t)}</a> (pdf 177.93 kb)</td></tr>' for t, url in supplementary
    )
    main = f"""<h1>{html.escape(h1)}</h1>
<p><i>Navigointi</i></p>{nav(mid, n)}
<h2>Kokousasian teksti</h2>
<div class="teksti">
<p>Asianumero 1312/10.03.02/2025</p>
<p>{html.escape(body_line)}</p>
<p class="Otsikko"><b>§ {pykala}</b></p>
<p class="Otsikko"><b>{html.escape(title)}</b></p>
<table><tr><td>Valmistelijat / lisätiedot:</td></tr><tr><td>Valmistelija Vilma</td></tr></table>
<p>etunimi.sukunimi@espoo.fi</p>
<p>Puhelinnumero 09 816 21</p>
{sections}
{heading("Liitteet", "h")}
<table><tr><th>Numero</th><th>Otsikko</th></tr>{att_rows}</table>
{heading("Oheismateriaali", "h") if supplementary else ""}
{f"<table><tr><th>Otsikko</th></tr>{sup_rows}</table>" if supplementary else ""}
<p>Tiedoksi</p>
</div>
<p><i>Navigointi</i></p>{nav(mid, n)}"""
    return page(h1, "Kokousasia", main)


def item_simple(mid: str, n: int, date: str, pykala: int, title: str, stage: str = "Pöytäkirja") -> str:
    final = stage == "Pöytäkirja"
    sections = f"""<p>Päätösehdotus Esittelijä</p>
<p>Puheenjohtaja</p>
<p>Valtuusto toteaa kokouksen laillisesti koolle kutsutuksi ja päätösvaltaiseksi.</p>
{heading("Käsittely", "p") if final else ""}
{"<p>Ei puheenvuoroja.</p>" if final else ""}
{heading("Päätös", "p") if final else ""}
{"<p>Valtuusto:</p><p>Päätösehdotus hyväksyttiin yksimielisesti.</p>" if final else ""}"""
    return item(f"Valtuusto  {stage} {date}/Pykälä {pykala}", mid, n, f"Valtuusto {date} § {pykala}",
                pykala, title, sections)  # fmt: skip


def item_olari() -> str:
    mid, n = "20261715", 13
    sections = f"""<p>Päätösehdotus Esittelijä</p>
<p>Kaupunginhallitus</p>
<p>Valtuusto merkitsee selostusosan tiedoksi vastauksena valtuutettu Eino Esimerkin sekä 25 muun valtuutetun 24.3.2025 jättämään valtuustoaloitteeseen ja toteaa valtuustoaloitteen loppuun käsitellyksi.</p>
{heading("Käsittely", "h")}
<p>Esimerkki Mallisen ym.  kannattamana teki seuraavan toivomuksen:</p>
<p>Valtuusto toivoo, että kaupunki ei sulje pois Olarin uimahallin kunnostamista ja uudelleen avaamista myöhemmin.</p>
<p>Keskustelun päätyttyä puheenjohtaja totesi kaupunginhallituksen ehdotuksen tulleen hyväksytyksi yksimielisesti.</p>
<p>Puheenjohtaja tiedusteli, voidaanko Esimerkin ehdotus yksimielisesti hyväksyä. Koska ehdotusta vastustettiin, puheenjohtaja totesi, että on äänestettävä.</p>
<p>Puheenjohtaja ehdotti, että äänestyksessä ne, jotka kannattavat Esimerkin ehdotusta, äänestävät jaa ja ne, jotka vastustavat sitä, äänestävät ei. Valtuusto hyväksyi puheenjohtajan ehdotuksen.</p>
<p>Äänestyksessä valtuusto 30 äänellä 41 ääntä vastaan, 4 äänestäessä tyhjää hylkäsi Esimerkin ehdotuksen. Äänestyslista on pöytäkirjan liitteenä.</p>
{heading("Päätös", "h")}
<p>Valtuusto:</p>
<p>Kaupunginhallituksen ehdotus hyväksyttiin yksimielisesti.</p>
{heading("Selostus", "h")}
<p><b>Valtuustoaloite</b></p>
<p>Valtuutettu Eino Esimerkki ja 25 muuta valtuutettua ovat jättäneet 24.3.2025 aloitteen Olarin uimahallin avaamiseksi.</p>
<p>Lisätietoja antaa Valmistelija Vilma, puh. 043 824 5678.</p>
{heading("Päätöshistoria", "h")}
<p><b>Kaupunginhallituksen konserni- ja tilajaosto 23.03.2026 § 30</b></p>
<p>Päätösehdotus Esittelijä: Kaupunkiympäristön toimialajohtaja Johtaja Jussi</p>
<p>Kaupunginhallituksen konserni- ja tilajaosto ehdottaa kaupunginhallitukselle ja edelleen valtuustolle, että valtuusto merkitsee selostusosan tiedoksi.</p>
<p>Käsittely</p>
<p>Testaaja Harjoituksen kannattamana ehdotti, että asia palautetaan uudelleen valmisteltavaksi.</p>
<p>Puheenjohtaja totesi kaupunginhallituksen konserni- ja tilajaoston 4 äänellä 4 ääntä vastaan yhden äänestäessä tyhjää hyväksyneen Testaajan palautusehdotuksen. Puheenjohtajan ääni ratkaisi äänestyksen. Äänestyslista on pöytäkirjan liitteenä.</p>
<p>Päätös</p>
<p>Konserni- ja tilajaosto: Asia palautettiin uudelleen valmisteltavaksi.</p>
<p><b>Kaupunginhallitus 17.08.2026 § 266</b></p>
<p>Päätösehdotus Esittelijä: Kaupunkiympäristön toimialajohtaja Johtaja Jussi</p>
<p>Kaupunginhallitus esittää valtuustolle, että valtuusto merkitsee selostusosan tiedoksi.</p>
<p>Käsittely</p>
<p>Päätös</p>
<p>Kaupunginhallitus: Esittelijän ehdotus hyväksyttiin yksimielisesti.</p>"""
    return item("Valtuusto  Pöytäkirja 21.09.2026/Pykälä 132", mid, n, "Valtuusto 21.09.2026 § 132", 132,
                "Valtuustoaloite kaupungin ryhtymisestä tarvittaviin toimiin Olarin uimahallin avaamiseksi",
                sections,
                [("Liite 1 Olarin uimahallin valokuvakooste 8.6.2026", f"{KOKOUS}/{mid}-{n}-357076.PDF"),
                 ("Liite 2 Äänestyslista § 132", f"{KOKOUS}/{mid}-{n}-375914.PDF")],
                [("Oheismateriaali 1 Valtuustoaloite Olarin uimahallin avaamiseksi", f"{KOKOUS}/{mid}-{n}-352661.PDF")])  # fmt: skip


BUDGET = [  # (proposer, label, jaa, ei, tyhjä, verb)
    ("Immonen", "Immonen", 38, 36, 1, "hyväksyi"),
    ("Hopsu", "Hopsu 3.2", 34, 39, 2, "hylkäsi"),
    ("Hopsu", "Hopsu 3.3.", 40, 33, 2, "hyväksyi"),
    ("Nurminen", "Nurminen", 35, 38, 2, "hylkäsi"),
    ("Nevanlinna", "Nevanlinna 3.6", 39, 34, 2, "hyväksyi"),
    ("Nevanlinna", "Nevanlinna 3.7", 44, 31, 0, "hyväksyi"),
]


def item_budget() -> str:
    mid, n = "20251553", 3
    deliberation = []
    for i, (_, _, jaa, ei, tyhja, verb) in enumerate(BUDGET, start=1):
        blank = f" ja {tyhja} äänestäessä tyhjää" if tyhja else ""
        deliberation.append(
            f"<p>{i}. Puheenjohtaja ehdotti, että äänestyksessä ne, jotka kannattavat ehdotusta, äänestävät jaa "
            f"ja ne, jotka vastustavat sitä, äänestävät ei. Valtuusto hyväksyi puheenjohtajan ehdotuksen.</p>"
            f"<p>Äänestyksessä valtuusto {jaa} äänellä {ei} ääntä vastaan{blank} {verb} ehdotuksen. "
            f"Äänestyslista on pöytäkirjan liitteenä.</p>"
        )
    sections = f"""<p>Päätösehdotus Esittelijä</p>
<p>Kaupunginhallitus</p>
<p>Valtuusto hyväksyy vuoden 2026 talousarvion ja vuosien 2026–2028 taloussuunnitelman.</p>
{heading("Käsittely", "p")}
{"".join(deliberation)}
{heading("Päätös", "p")}
<p>Valtuusto:</p>
<p>Kaupunginhallituksen ehdotus hyväksyttiin äänestysten jälkeen muutettuna.</p>
{heading("Selostus", "p")}
<p>Talousarvio on liitteenä.</p>"""
    title = "Vuoden 2026 talousarvion ja taloussuunnitelman hyväksyminen (Osittain pöydälle 4.12.2025)"
    page_html = item("Valtuusto  Pöytäkirja 08.12.2025/Pykälä 167", mid, n, "Valtuusto 08.12.2025 § 167", 167,
                     title, sections, [("Liite 1Äänestyslistat § 167", f"{KOKOUS}/{mid}-{n}-330209.PDF")])  # fmt: skip
    # The real page repeats the attachment list without links below the first one.
    return page_html.replace(
        "</table>\n\n\n<p>Tiedoksi</p>",
        "</table>\n<table><tr><th>Numero</th><th>Otsikko</th></tr><tr><td>1</td><td>Äänestyslistat § 167</td></tr></table>\n<p>Tiedoksi</p>",
    )


# -- vote PDFs ----------------------------------------------------------------------------


def ballots(jaa: int, ei: int, tyhja: int, seed: int) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    names = NAMES[:]
    rng.shuffle(names)
    out = [(n, "Ei") for n in names[:ei]] + [(n, "Jaa") for n in names[ei : ei + jaa]]
    return out + [(n, "Tyhjä") for n in names[ei + jaa : ei + jaa + tyhja]]


def pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    y = 800
    for line in lines:
        if y < 60:
            c.showPage()
            y = 800
        c.setFont("Helvetica", 10)
        c.drawString(50, y, line)
        y -= 14
    c.showPage()
    c.save()
    return buf.getvalue()


def options(rows: list[tuple[str, str]], order: list[str]) -> list[str]:
    counts = {c: sum(1 for _, x in rows if x == c) for c in order}
    return [f"{c} {counts[c]}" for c in order]


def pdf_olari() -> bytes:
    rows = ballots(30, 41, 4, seed=132)
    lines = ["Cloudmeeting Äänestystulosraportti", "21.09.2026", "Äänestystulosraportti",
             "Toimielin Valtuusto - Fullmäktige", "Kokous Valtuusto 21.09.2026",
             "§ 132 Valtuustoaloite kaupungin ryhtymisestä tarvittaviin",
             "toimiin Olarin uimahallin avaamiseksi", "Esimerkki Jaa / vastaan Ei / Tyhjä ",
             "Annettuja ääniä yhteensä 75", "Äänet vaihtoehdoittain", *options(rows, ["Ei", "Jaa", "Tyhjä"]),
             "Äänet äänestäjittäin", *(f"{n} {c} " for n, c in rows)]  # fmt: skip
    return pdf(lines)


def pdf_budget() -> bytes:
    lines = ["Cloudmeeting Äänestystulosraportti", "08.12.2025", "Äänestystulosraportti",
             "Toimielin Valtuusto - Fullmäktige", "Kokous Valtuusto 08.12.2025",
             "§ 167 Vuoden 2026 talousarvion ja taloussuunnitelman",
             "hyväksyminen (Osittain pöydälle 4.12.2025)"]  # fmt: skip
    for i, (_, label, jaa, ei, tyhja, _) in enumerate(BUDGET, start=1):
        rows = ballots(jaa, ei, tyhja, seed=167 + i)
        sep = ":" if i != 3 else ""
        lines += [f"{i}. Äänestys: Jaa{sep} {label} / Ei: vastaan / Tyhjä", "Annettuja ääniä yhteensä 75",
                  "Äänet vaihtoehdoittain", *options(rows, ["Jaa", "Ei", "Tyhjä"] if i % 2 else ["Ei", "Jaa", "Tyhjä"]),
                  "Äänet äänestäjittäin"]  # fmt: skip
        for name, choice in rows:
            if i == 2 and name == NAMES[0]:
                # a deputy printed with the member they replace, the choice on its own line
                lines += [DEPUTY, f"({name})", choice]
            else:
                lines.append(f"{name} {choice}")
    return pdf(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write("meeting_frames.html", meeting_frames(), "iso-8859-1")
    write("meetings-1.html", meetings("Valtuusto", {
        "2026": [("19.10.2026", "Esityslista", "20261743"), ("21.09.2026", "Pöytäkirja", "20261715")],
        "2025": [("08.12.2025", "Pöytäkirja", "20251553")],
        "2024": [("16.12.2024", "Pöytäkirja", "2024987")],
    }), "iso-8859-1")  # fmt: skip
    write("meetings-empty.html", meetings("Toimielin", {}), "iso-8859-1")
    write("meeting-20261715.html", meeting(
        "20261715", "Valtuusto  Pöytäkirja 21.09.2026 klo 17.30 - 19.53 ⁄ Tarkastettu  Valtuustotalo, Espoonkatu 5",
        "30.09.2026", "Pöytäkirja",
        [(1, 120, "Kokouksen laillisuuden ja päätösvaltaisuuden toteaminen", False),
         (2, 121, "Pöytäkirjan tarkastajien valinta", False),
         (13, 132, "Valtuustoaloite kaupungin ryhtymisestä tarvittaviin toimiin Olarin uimahallin avaamiseksi", True)],
        council_participants()))  # fmt: skip
    write("meeting-20251553.html", meeting(
        "20251553", "Valtuusto  Pöytäkirja 08.12.2025 klo 17.30 - 20:18 ⁄ Tarkastettu  Valtuustotalo, Espoonkatu 5",
        "15.12.2025", "Pöytäkirja",
        [(3, 167, "Vuoden 2026 talousarvion ja taloussuunnitelman hyväksyminen (Osittain pöydälle 4.12.2025)", True)],
        council_participants()))  # fmt: skip
    write("meeting-20261743.html", meeting(
        "20261743", "Valtuusto  Esityslista 19.10.2026 klo 17:30 -  Valtuustotalo, Espoonkatu 5", "08.10.2026",
        "Esityslista",
        [(1, 135, "Kokouksen laillisuuden ja päätösvaltaisuuden toteaminen", False),
         (2, 136, "Pöytäkirjan tarkastajien valinta", False)],
        council_participants()))  # fmt: skip
    write("item-20261715-1.html", item_simple("20261715", 1, "21.09.2026", 120,
                                               "Kokouksen laillisuuden ja päätösvaltaisuuden toteaminen"))  # fmt: skip
    write("item-agenda.html", item_simple("20261743", 1, "19.10.2026", 135,
                                          "Kokouksen laillisuuden ja päätösvaltaisuuden toteaminen", "Esityslista"))  # fmt: skip
    write("item-20261715-13.html", item_olari())
    write("item-20251553-3.html", item_budget())
    (OUT / "vote-20261715-13-375914.pdf").write_bytes(pdf_olari())
    (OUT / "vote-20251553-3-330209.pdf").write_bytes(pdf_budget())


if __name__ == "__main__":
    main()
