"""Generate reconstructed paatokset.hel.fi fixtures in tests/fixtures/helsinki (deterministic).

The cloud environment that built M1 could not reach paatokset.hel.fi, so these pages are
rebuilt by hand from the page structure inspected on 2026-10-11 (headings, labels, link shapes,
pager, vote blocks and tables, see PLAN.md §16 S1/S6). Text is shortened and member names are
fictional; counts match the real item (council 23.9.2026 § 261: 34 Jaa / 36 Ei / 15 Tyhjä /
0 Poissa). Replace them with recorded pages once a live run is possible
(tests/fixtures/helsinki/README.md).
"""

from __future__ import annotations

import html
import itertools
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "helsinki"
BASE = "https://paatokset.hel.fi"

FIRST = ["Aino", "Eero", "Helmi", "Ilmari", "Kerttu", "Lauri", "Mikko", "Noora", "Oona", "Pekka",
         "Riikka", "Sami", "Tuula", "Veikko", "Wilma", "Aleksi", "Elina"]  # fmt: skip
LAST = ["Esimerkki", "Kuvitteellinen", "Mallinen", "Testaaja", "Harjoitus", "Näyte", "Malli",
        "Kokeilu", "Luonnos", "Demonen"]  # fmt: skip
GROUPS = [
    "Kokoomuksen valtuustoryhmä",
    "Vihreä valtuustoryhmä",
    "Sosialidemokraattinen valtuustoryhmä",
    "Vasemmistoliiton valtuustoryhmä",
    "Perussuomalaisten valtuustoryhmä",
    "Ruotsalaisen kansanpuolueen valtuustoryhmä",
    "Keskustan valtuustoryhmä",
]

NAV = """
<header><nav class="main-menu"><ul>
<li><a href="/fi/paattajat/kaupunginvaltuusto">Kaupunginvaltuusto</a></li>
<li><a href="/fi/paattajat/kaupunginhallitus">Kaupunginhallitus</a></li>
<li><a href="/fi/paattajat/kaupunginhallituksen-konsernijaosto">Kaupunginhallituksen konsernijaosto</a></li>
<li><a href="/fi/paattajat/kaupunginhallituksen-elinkeinojaosto">Kaupunginhallituksen elinkeinojaosto</a></li>
<li><a href="/fi/paattajat/lautakunnat-ja-johtokunnat">Lautakunnat ja johtokunnat</a></li>
<li><a href="/fi/paattajat/viranhaltijat">Viranhaltijat</a></li>
<li><a href="/fi/asia">Asiat</a></li>
</ul></nav></header>
"""
FOOTER = """
<footer><h2>Helsingin kaupunki</h2><p>© Helsingin kaupunki</p><h2>Ota yhteyttä</h2>
<p><a href="https://www.hel.fi/fi/ota-yhteytta">Ota yhteyttä</a></p></footer>
"""


def page(title: str, main: str) -> str:
    return (
        '<!DOCTYPE html>\n<html lang="fi"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)} | Päätökset | Helsingin kaupunki</title>"
        '<script>window.drupalSettings={"x":1}</script></head>\n<body>'
        f'{NAV}<main id="main-content" class="layout-main">\n{main}\n</main>{FOOTER}</body></html>\n'
    )


def members(n: int, offset: int) -> list[tuple[str, str, str]]:
    """(first, last, group) — fictional, unique, sorted by surname like the source."""
    combos = list(itertools.product(LAST, FIRST))
    picked = [combos[(offset + i * 7) % len(combos)] for i in range(n)]
    out = [(f, l, GROUPS[(offset + i) % len(GROUPS)]) for i, (l, f) in enumerate(picked)]
    return sorted(out, key=lambda m: (m[1], m[0]))


def committees() -> str:
    groups = {
        "Kasvatuksen ja koulutuksen toimiala": [
            ("kasvatus-ja-koulutuslautakunta", "Kasvatus- ja koulutuslautakunta"),
            ("kasvatus-ja-koulutuslautakunnan-suomenkielinen-jaosto",
             "Kasvatus- ja koulutuslautakunnan suomenkielinen jaosto"),
        ],
        "Kaupunkiympäristön toimiala": [
            ("liikenneliikelaitoksen-johtokunta", "Liikenneliikelaitoksen johtokunta"),
            ("kaupunkiymparistolautakunnan-ymparisto-ja-lupajaosto",
             "Kaupunkiympäristölautakunnan ympäristö- ja lupajaosto"),
            ("kaupunkiymparistolautakunta", "Kaupunkiympäristölautakunta"),
        ],
        "Keskushallinto": [
            ("tarkastuslautakunta", "Tarkastuslautakunta"),
            ("rakentamispalveluliikelaitoksen-johtokunta", "Rakentamispalveluliikelaitoksen johtokunta (Stara)"),
            ("keskusvaalilautakunta", "Keskusvaalilautakunta"),
        ],
        "Sosiaali-, terveys- ja pelastustoimiala": [
            ("sosiaali-terveys-ja-pelastuslautakunta", "Sosiaali-, terveys- ja pelastuslautakunta"),
            ("sosiaali-terveys-ja-pelastuslautakunnan-yksiloasioiden-jaosto",
             "Sosiaali-, terveys- ja pelastuslautakunnan yksilöasioiden jaosto"),
        ],
    }  # fmt: skip
    parts = ["<h1>Lautakunnat ja johtokunnat</h1>"]
    for heading, links in groups.items():
        parts.append(f"<h2>{html.escape(heading)}</h2><ul>")
        parts += [f'<li><a href="/fi/paattajat/{s}">{html.escape(n)}</a></li>' for s, n in links]
        parts.append("</ul>")
    return page("Lautakunnat ja johtokunnat", "\n".join(parts))


def listing(rows: list[tuple[str, str, str]], page_no: int, last_page: int) -> str:
    parts = ['<h1>Asiakirjat: Helsingin kaupunginvaltuusto</h1><div class="count">203 asiakirjaa</div>',
             '<div class="filter"><span>Kaikki vuodet</span><span>2026</span><span>2025</span></div>',
             '<ul class="document-list">']  # fmt: skip
    for code, label, date in rows:
        frag = "#paatostiedote" if label.startswith("Esityslista") else ""
        parts.append(
            f'<li class="document-row"><h3><a href="/fi/paattajat/kaupunginvaltuusto/asiakirjat/{code}{frag}">'
            f"{label}</a></h3><div>Päätöksentekopäivä: {date}</div>"
            + ("<div>Lue päätöstiedote</div>" if frag else "")
            + "</li>"
        )
    parts.append('</ul><nav class="pager"><ul>')
    if page_no > 0:
        parts.append(f'<li><a href="?page={page_no - 1}">Edellinen</a></li>')
    parts += [f'<li><a href="?page={i}">{i + 1}</a></li>' for i in range(last_page + 1)]
    if page_no < last_page:
        parts.append(f'<li><a href="?page={page_no + 1}">Seuraava</a></li>')
    parts.append("</ul></nav>")
    return page("Asiakirjat", "\n".join(parts))


def meeting(kind: str, number: str, date: str, rows: list[tuple[int, int | None, str, str]],
            bulletin: list[str] | None, transcript: str | None, video: str | None) -> str:  # fmt: skip
    parts = [
        f"<h1>{kind} Kaupunginvaltuusto {number} {date}</h1>",
        f'<div class="meeting-meta"><p>Kokousaika: {date} - 18:00</p>'
        "<p>Kokouspaikka: Valtuustosali, Aleksanterinkatu 20</p></div>",
        "<p>Pöytäkirja korvaa ilmestyessään esityslistan ja päätöstiedotteen.</p>",
        '<h2>Asialista</h2><ol class="agenda">',
    ]
    for ordinal, pykala, title, href in rows:
        num = f"{ordinal}. / {pykala} §" if pykala else f"{ordinal}."
        parts.append(f'<li><a href="{href}"><span>{num}</span> {html.escape(title)}</a></li>')
    parts.append("</ol>")
    if bulletin is not None:
        parts.append("<h2>Päätöstiedote: Kaupunginvaltuusto</h2>")
        parts += [f"<p>{html.escape(b)}</p>" for b in bulletin]
    if video:
        parts.append(f'<div class="video"><iframe src="{video}" title="Helsinki-kanava"></iframe></div>')
    parts.append(
        '<div class="downloads"><a href="https://ahjojulkaisu.hel.fi/7826F40B-88C3-C5C5-8EE8-A0A3A8B00000.pdf">'
        "Lataa tulostusversio (pdf)</a>"
    )
    if transcript:
        parts.append(f'<a href="{transcript}">Lataa kokouksen keskustelupöytäkirja (pdf)</a>')
    parts.append('</div><h2>Jaa</h2><p><a href="https://www.facebook.com/sharer">Facebook</a></p>')
    return page(f"Kaupunginvaltuusto {number}", "\n".join(parts))


def vote_text(n: str, jaa: str, ei: str, groups: dict[str, list[str]], result: str) -> str:
    parts = [
        f"<h4>{n} äänestys</h4>",
        f"<p>JAA-ehdotus: {html.escape(jaa)}<br>EI-ehdotus: {html.escape(ei)}</p>",
    ]
    for label, names in groups.items():
        parts.append(f"<p>{label}: {len(names)}</p>")
        if names:
            parts.append(f"<p>{', '.join(names)}</p>")
    parts.append(f"<p>{html.escape(result)}</p>")
    return "\n".join(parts)


def board_names(n: int, offset: int) -> list[str]:
    return [f"{f} {l}" for f, l, _ in members(n, offset)]


def item_with_vote() -> str:
    council = members(85, 3)
    jaa, ei, tyhja = council[:34], council[34:70], council[70:]
    by = {"Jaa-äänet": jaa, "Ei-äänet": ei, "Tyhjä": tyhja, "Poissa": []}
    text_groups = {k: [f"{f} {l}" for f, l, _ in v] for k, v in by.items()}
    # The table lists members per choice as "Sukunimi, Etunimi" with their council group.
    tables = []
    for label, choice in (("Jaa-äänet", "Jaa"), ("Ei-äänet", "Ei"), ("Tyhjä", "Tyhjä"), ("Poissa", "Poissa")):
        rows = by[label]
        tables.append(f"<h5>{len(rows)} {choice}</h5>")
        if rows:
            body = "".join(
                f"<tr><td>{html.escape(l)}, {html.escape(f)}</td><td>{html.escape(g)}</td></tr>"
                for f, l, g in rows
            )
            tables.append(
                f"<table><thead><tr><th>Jäsen</th><th>Valtuustoryhmä</th></tr></thead><tbody>{body}</tbody></table>"
                f'<button class="close">Sulje alue: {len(rows)} {choice} Sulje</button>'
            )
    summary = "".join(
        f"<tr><td>{g}</td><td>{sum(1 for m in jaa if m[2] == g)}</td><td>{sum(1 for m in ei if m[2] == g)}</td>"
        f"<td>{sum(1 for m in tyhja if m[2] == g)}</td><td>0</td></tr>"
        for g in GROUPS
    )
    tables.append(
        "<h5>Äänestystulos valtuustoryhmittäin</h5><table><thead><tr><th>Valtuustoryhmä</th><th>Jaa</th>"
        f"<th>Ei</th><th>Tyhjä</th><th>Poissa</th></tr></thead><tbody>{summary}</tbody></table>"
    )

    board = board_names(15, 11)
    committee = board_names(13, 29)
    main = f"""
<div class="case-header">
<h1>Hankesuunnitelma, Länsisataman pikaraitiotie, kaupunkiympäristön toimiala</h1>
<div class="case-meta"><span class="label">Diaarinumero</span> <span>HEL 2026-008342</span> <span>Liikenne</span></div>
<div class="decision-picker"><ul>
<li><a href="/fi/asia/hel-2026-008342?paatos=6c1e0a7d-0000-4000-8000-000000000001">Helsingin kaupunginvaltuusto 14/23.09.2026</a></li>
<li><a href="/fi/asia/hel-2026-008342?paatos=6c1e0a7d-0000-4000-8000-000000000002">Helsingin kaupunginhallitus 30/07.09.2026</a></li>
<li><a href="/fi/asia/hel-2026-008342?paatos=6c1e0a7d-0000-4000-8000-000000000003">Kaupunkiympäristölautakunta 23/18.08.2026</a></li>
</ul></div>
<div class="decision-error" hidden><p>Virhe päätöstä ladattaessa</p><p>Something went wrong loading decision. Try again.</p></div>
<p class="notice">Asialla on uudempia käsittelyjä</p>
</div>
<article class="decision">
<h2>Länsisataman pikaraitiotien hankesuunnitelma</h2>
<div class="decision-meta"><p>13. / 261 §</p><p>Kaupunginvaltuusto</p></div>
<div class="section"><h3>Päätös</h3>
<p>Kaupunginvaltuusto päätti hyväksyä Länsisataman pikaraitiotien hankesuunnitelman (liite 1) siten, että hankkeen kokonaiskustannusarvio on 48 milj. euroa (MAKU 129,32; 2015=100).</p></div>
<div class="section"><h3>Käsittely</h3>
<h4>Toivomusponsi</h4>
<p>Valtuutettu Otso Kivekäs teki seuraavan toivomusponsiehdotuksen:</p>
<p>Kaupunginvaltuusto edellyttää, että selvitetään mahdollisuus jatkaa Helsingin yliopiston metroaseman pohjoisen sisäänkäynnin valmistelua.</p>
<p>Kannattaja: Valtuutettu Silvia Modig</p>
<p>Kaupunginvaltuusto hyväksyi kaupunginhallituksen ehdotuksen.</p>
{
        vote_text(
            "3",
            "Valtuutettu Otso Kivekkään ehdottama toivomusponsi JAA, vastustus EI",
            "Vastustaa",
            text_groups,
            "Kaupunginvaltuusto ei hyväksynyt valtuutettu Otso Kivekkään ehdottamaa toivomuspontta.",
        )
    }
</div>
<p><a href="#aanestystulokset">Katso äänestystulos taulukkona</a></p>
<div class="accordion" id="aanestystulokset"><button>Avaa kaikki</button>
<h3>Äänestystulokset</h3>
<h4>Äänestys 1</h4>
{"".join(tables)}
<button>Sulje alue: Äänestystulokset Sulje</button>
</div>
<div class="section"><h3>Päätösehdotus</h3><p>Kaupunginvaltuusto päättänee hyväksyä hankesuunnitelman.</p></div>
<div class="section"><h3>Esittelijän perustelut</h3>
<h4>Kustannukset ja talousvaikutukset</h4><p>Hankkeen kustannusarvio on 48 milj. euroa.</p>
<h4>Toimivalta</h4><p>Hallintosäännön mukaan kaupunginvaltuusto päättää yli 10 milj. euron hankesuunnitelmista.</p>
<p>Lisätietoja: <a href="mailto:etu.suku@hel.fi">etu.suku@hel.fi</a>, puhelin 09 310 12345</p>
<p>Aiempi päätös: <a href="/fi/asia/hel-2024-009714?paatos=ec1597aa-35b8-4cda-b865-7db2aa8d2740">yleissuunnitelma</a></p>
</div>
<div class="section"><h3>Päätöshistoria</h3>
<h2>Kaupunginhallitus 07.09.2026 § 609</h2>
<p>HEL 2026-008342 T 08 00 02</p>
<h3>Päätös</h3><p>Kaupunginhallitus päätti esittää kaupunginvaltuustolle hankesuunnitelman hyväksymistä.</p>
<h3>Käsittely</h3>
<p>07.09.2026 Esittelijän ehdotuksesta poiketen</p>
<p>Vastaehdotus 1:</p><p>Paavo Arhinmäki</p><p>Lisätään kappaleen 16 loppuun virke raitiolinjan 12 palauttamisesta.</p><p>Kannattaja: Niilo Toivonen</p>
{
        vote_text(
            "1.",
            "Esittelijän ehdotus",
            "Vastaehdotus 2",
            {"Jaa-äänet": board[:6], "Ei-äänet": board[6:15]},
            "Kaupunginhallitus hyväksyi vastaehdotuksen äänin 6 - 9.",
        )
    }
{
        vote_text(
            "2.",
            "Esittelijän ehdotus",
            "Vastaehdotus 3",
            {"Jaa-äänet": [], "Ei-äänet": board[:12], "Tyhjä": board[12:15]},
            "Kaupunginhallitus hyväksyi esittelijän ehdotuksen.",
        )
    }
{
        vote_text(
            "3.",
            "Esittelijän ehdotus",
            "Vastaehdotus 4",
            {"Jaa-äänet": board[:9], "Ei-äänet": board[9:14], "Tyhjä": board[14:15]},
            "Kaupunginhallitus hyväksyi esittelijän ehdotuksen äänin 9 - 5 (1 tyhjä).",
        )
    }
<p>31.08.2026 Pöydälle</p>
<h3>Esittelijä</h3><p>kansliapäällikkö</p><p>Jukka-Pekka Ujula</p>
<h2>Kaupunkiympäristölautakunta 18.08.2026 § 402</h2>
<h3>Esitys</h3><p>Kaupunkiympäristölautakunta esitti kaupunginhallitukselle hankesuunnitelman hyväksymistä.</p>
<h3>Käsittely</h3>
{
        vote_text(
            "1",
            "Esittelijän ehdotus",
            "Vastaehdotus 1",
            {"Jaa-äänet": committee[:8], "Ei-äänet": committee[8:13], "Tyhjä": [], "Poissa": []},
            "Lautakunta hyväksyi esittelijän ehdotuksen.",
        )
    }
{
        vote_text(
            "2",
            "Esittelijän ehdotus",
            "Vastaehdotus 2",
            {"Jaa-äänet": committee[:5], "Ei-äänet": committee[5:13], "Tyhjä": [], "Poissa": []},
            "Lautakunta hyväksyi vastaehdotuksen.",
        )
    }
{
        vote_text(
            "3",
            "Esittelijän ehdotus",
            "Vastaehdotus 3",
            {
                "Jaa-äänet": committee[:7],
                "Ei-äänet": committee[7:12],
                "Tyhjä": committee[12:13],
                "Poissa": [],
            },
            "Lautakunta hyväksyi esittelijän ehdotuksen.",
        )
    }
<h3>Esittelijä</h3><p>kaupunkiympäristön toimialajohtaja</p><p>Ville Lehmuskoski</p>
<h3>Lisätiedot</h3><p>Etu Suku, projektinjohtaja, puhelin: 09 310 12345</p><p>etu.suku@hel.fi</p>
</div>
<div class="section"><h3>Muutoksenhaku</h3><p>Kunnallisvalitus Helsingin hallinto-oikeuteen 30 päivän kuluessa.</p></div>
<div class="section"><h3>Esittelijä</h3><p>Titteli</p><p>Kaupunginhallitus</p></div>
<div class="section"><h3>Lisätietojen antaja</h3><p>Anna Esimerkki, liikenneinsinööri, puhelin: 09 310 37000</p><p>anna.esimerkki@hel.fi</p></div>
</article>
<h2>Sanat tai yhteystieto hukassa?</h2><p><a href="/fi/sanasto">Päätöksenteon sanasto</a></p>
<h3>Liitteet (pdf)</h3>
<ul>
<li><a href="https://ahjojulkaisu.hel.fi/040D6AF5-8943-C604-A486-9EF4AB800000.pdf">Länsisataman pikaraitiotien hankesuunnitelmaraportti</a></li>
<li><a href="https://ahjojulkaisu.hel.fi/9DED6DE3-AE1D-CFDB-9573-9EF3E0A00000.pdf">Länsisataman pikaraitiotien perushankkeen vaikutusten arviointi</a></li>
<li><a href="https://ahjojulkaisu.hel.fi/39945EE4-B449-CBA6-9C20-9ECF18200000.pdf">Länsisataman pikaraitiotie liittyvät hankkeet</a></li>
</ul>
<p><a href="https://ahjojulkaisu.hel.fi/7826F40B-88C3-C5C5-8EE8-A0A3A8B00001.pdf">Lataa tulostusversio (pdf)</a></p>
"""  # noqa: E501
    return page("Hankesuunnitelma, Länsisataman pikaraitiotie", main)


def item_roll_call(error: bool = False) -> str:
    decision = (
        ""
        if error
        else """<div class="section"><h3>Päätös</h3>
<p>Kaupunginvaltuusto totesi kokouksen kuntalaissa ja hallintosäännössä edellytetyssä järjestyksessä koolle kutsutuksi ja päätösvaltaiseksi.</p>
<h4>Nimenhuuto ja estyneet</h4>
<p>Aino Esimerkki, tilalle Eero Mallinen</p><p>Helmi Testaaja, tilalle Lauri Näyte</p></div>
<div class="section"><h3>Päätösehdotus</h3><p>Kaupunginvaltuusto merkitsee tiedoksi ilmoitetut esteet ja toteaa kokouksen lailliseksi ja päätösvaltaiseksi.</p></div>
<div class="section"><h3>Muutoksenhaku</h3><h4>MUUTOKSENHAKUKIELTO</h4><p>Tähän päätökseen ei saa hakea muutosta. Kuntalaki 136 §.</p></div>"""  # noqa: E501
    )
    # A failed load renders the error notice and none of the decision's sections.
    main = f"""
<h1>Nimenhuuto, laillisuus ja päätösvaltaisuus</h1>
<div class="case-meta"><span>Hallintoasiat</span></div>
<div class="decision-error"{"" if error else " hidden"}><p>Virhe päätöstä ladattaessa</p><p>Something went wrong loading decision. Try again.</p></div>
<p><a href="/fi/paattajat/kaupunginvaltuusto/asiakirjat/02900202614">Kokouksen muut asiat</a></p>
<article class="decision">
<h2>Nimenhuuto, laillisuus ja päätösvaltaisuus</h2>
<div class="decision-meta"><p>1. / 249 §</p><p>Kaupunginvaltuusto</p></div>
{decision}
</article>
<h2>Sanat tai yhteystieto hukassa?</h2>
<p><a href="https://ahjojulkaisu.hel.fi/968644D4-3321-CA71-A311-A0A3A5900000.pdf">Lataa tulostusversio (pdf)</a></p>
"""  # noqa: E501
    return page("Nimenhuuto", main)


def item_forwarded() -> str:
    """A committee forwarding a matter: the decision is headed "Esitys", the proposal
    "Esitysehdotus"; presenter and contacts use "Nimi …" headings with "Titteli …" lines."""
    main = """
<h1>Luonnonsuojelualueohjelma 2025-2040, kaupunkiympäristön toimiala</h1>
<div class="case-meta"><span>Diaarinumero</span> <span>HEL 2024-011399</span> <span>Ympäristöasia</span>
<span>Seuraava käsittely</span><p>Virhe päätöstä ladattaessa</p></div>
<article class="decision">
<h2>Kaupunkiympäristölautakunnan esitys kaupunginhallitukselle luonnonsuojelualueohjelman hyväksymisestä</h2>
<div class="decision-meta"><p>4. / 4 §</p><p>Lautakunnat ja johtokunnat</p><p>Päättäjä: Kaupunkiympäristölautakunta</p></div>
<h3>Esitys</h3><p>Kaupunkiympäristölautakunta päätti panna asian pöydälle.</p>
<h3>Käsittely</h3><p>Asian aikana kuultavina olivat tiimipäällikkö ja yleiskaavasuunnittelija.</p>
<h3>Esitysehdotus</h3><p>Kaupunkiympäristölautakunta esittää kaupunginhallitukselle ohjelman hyväksymistä.</p>
<h3>Esittelijän perustelut</h3>
<h3>Taustaa</h3><p>Helsingin maapinta-alasta noin 40 % on luontoalueita. Työavain KASKO-01-1029-25.</p>
<h4>Tavoitteet</h4><p>Ohjelman tavoitteena on nostaa suojelualueiden osuutta.</p>
<h3>Muutoksenhaku</h3><p>Päätös tullut nähtäväksi 20.01.2025</p><h4>MUUTOKSENHAKUKIELTO</h4><p>Tähän päätökseen ei saa hakea muutosta.</p>
<h3>Esittelijä</h3><h4>Nimi Ville Lehmuskoski</h4><p>Titteli Kaupunkiympäristön toimialajohtaja</p>
<h3>Lisätietojen antajat</h3><h4>Nimi Etu Suku</h4><p>Titteli Ympäristösuunnittelija Puhelinnumero 09 310 12345 Sähköposti etu.suku@hel.fi</p>
</article>
<h3>Liitteet (pdf)</h3><ul><li><a href="https://ahjojulkaisu.hel.fi/0000AAAA-0000-0000-0000-000000000001.pdf">1. Luonnonsuojelualueohjelma 2025-2040, raportti</a></li></ul>
<h2>Sanat tai yhteystieto hukassa?</h2><p>Päätöksenteon sanakirja selventää termejä.</p>
"""
    return page("Luonnonsuojelualueohjelma", main)


def item_swedish() -> str:
    """The Swedish-language sections publish their decisions in Swedish."""
    main = """
<h1>Val av medlem i direktionen för Nordsjö lågstadieskola</h1>
<article class="decision">
<h2>Val av medlem i direktionen för Nordsjö lågstadieskola</h2>
<div class="decision-meta"><p>4. / 4 §</p></div>
<h3>Beslut</h3><p>Svenska sektionen beslutade bevilja befrielse enligt anhållan och utse en ny medlem.</p>
<h3>Beslutsförslag</h3><p>Beslutet stämmer överens med förslaget.</p>
<h3>Föredragandens motiveringar</h3><p>Medlemmen har anhållit om befrielse från uppdraget.</p>
<h3>Muutoksenhaku</h3><h4>Anvisningar om hur man begär omprövning</h4><p>Den som är missnöjd med beslutet kan framställa en begäran.</p>
<h3>Esittelijä</h3><h4>Nimi Niclas Grönholm</h4><p>Titteli Direktör för den svenska servicehelheten</p>
<h3>Lisätietojen antaja</h3><h4>Nimi Heidi Exempel</h4><p>Titteli Rektor Puhelinnumero 09 310 71728 Sähköposti heidi.exempel@hel.fi</p>
</article>
<h2>Sanat tai yhteystieto hukassa?</h2>
"""
    return page("Val av medlem", main)


def write(name: str, text: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(text, encoding="utf-8")


def main() -> None:
    write("lautakunnat-ja-johtokunnat.html", committees())
    page0 = [("02900202615", "Esityslista 15 - 2026", "7.10.2026"),
             ("02900202614", "Esityslista 14 - 2026", "23.9.2026"),
             ("02900202613", "Pöytäkirja 13 - 2026", "9.9.2026")]  # fmt: skip
    page1 = [("0290020251", "Pöytäkirja 1 - 2025", "15.1.2025"),
             ("02900202420", "Pöytäkirja 20 - 2024", "11.12.2024"),
             ("02900202419", "Pöytäkirja 19 - 2024", "27.11.2024")]  # fmt: skip
    write("listing-kaupunginvaltuusto-0.html", listing(page0, 0, 8))
    write("listing-kaupunginvaltuusto-1.html", listing(page1, 1, 8))
    rows14 = [
        (1, 249, "Nimenhuuto, laillisuus ja päätösvaltaisuus", f"{BASE}/fi/asia/26ac134e-452f-43dd-a7e2-42600821c38e"),
        (2, 250, "Pöytäkirjan tarkastajien valinta", f"{BASE}/fi/asia/a2811877-54a9-cb9a-b604-a11a3c700002"),
        (13, 261, "Länsisataman pikaraitiotien hankesuunnitelma",
         f"{BASE}/fi/asia/hel-2026-008342?paatos=6c1e0a7d-0000-4000-8000-000000000001"),
    ]  # fmt: skip
    write(
        "meeting-02900202614.html",
        meeting("Pöytäkirja", "14/2026", "23.09.2026", rows14, None,
                f"{BASE}/sites/default/files/2026-10/14_kvsto_23092026.pdf",
                "https://events.icareus.com/web/helsinkikanava/player?eventId=12345"),
    )  # fmt: skip
    rows15 = [
        (1, None, "Nimenhuuto, laillisuus ja päätösvaltaisuus", f"{BASE}/fi/asia/09ccd9f4-59b0-49ff-8244-ff806f4cb0c7"),
        (2, None, "Pöytäkirjan tarkastajien valinta", f"{BASE}/fi/asia/b15b1750-75a8-404f-b751-4718e45d2238"),
        (3, None, "Kuntalaisaloitteet ja nuorten aloitteet",
         f"{BASE}/fi/asia/hel-2026-000038?paatos=3409feea-d6fc-4d1a-a9c9-a29f0c94f2e3"),
    ]  # fmt: skip
    write(
        "meeting-02900202615.html",
        meeting("Esityslista", "15/2026", "07.10.2026", rows15,
                ["1. Nimenhuuto, laillisuus ja päätösvaltaisuus", "Ehdotuksen mukaan.",
                 "2. Pöytäkirjan tarkastajien valinta", "Ehdotuksen mukaan.",
                 "3. Kuntalaisaloitteet ja nuorten aloitteet", "Ehdotuksen mukaan."], None, None),
    )  # fmt: skip
    write("item-hel-2026-008342.html", item_with_vote())
    write("item-roll-call.html", item_roll_call())
    write("item-load-error.html", item_roll_call(error=True))
    write("item-forwarded.html", item_forwarded())
    write("item-swedish.html", item_swedish())


if __name__ == "__main__":
    main()
