"""Page and PDF parsers for Triplan Tweb at paatokset.vantaa.fi (PLAN.md §7.4). Pure functions.

Structure recorded on 2026-10-13 (PLAN.md §16, S3):

- `/ktwebscr/pk_tek_tweb.htm`: the body dropdown (`<select>`, printed twice on the page) maps
  "kirjaamo" ids to names;
- minutes list `/ktwebbin/dbisa.dll/ktwebscr/pk_kokl_tweb.htm?+kirjaamo={id}` and agenda list
  `/ktwebscr/epj_kokl_tweb.htm?+kirjaamo={id}`: rows "{Body}: {Body}" with a link
  "d.m.yyyy hh:mm" to `pk_asil_tweb.htm?bid=` (minutes) or `epj_asil_tweb.htm?bid=` (agenda);
- meeting page: a "Kooste (PDF)" row with the compiled minutes, then a table § | Otsikko |
  Liitteet. Rows without § are the cover page ("Pöytäkirjan kansilehti") and appeal instructions.
  Item titles on board agendas end with the presenter's initials ("/ PT", "/PT (kvalt)");
- item document `fileshow?doctype=3&docid=`: a PDF holding the whole case: title, diary number,
  initials, background, then one block per handling headed "{Body} d.m.yyyy § n" with
  "… esitys:", "Käsittely:" and "Päätös:", then "Liite:" titles, "Muutoksenhakuohje" and
  "Lisätiedot:" contact lines (dropped). The last block is the meeting's own;
- cover page PDF: "Aika d.m.yyyy klo hh.mm–hh.mm", "Paikka …" and the participants in two
  columns ("Surname First[, role] x|-" with an optional "(klo … § …)" note) for members, then
  "Varajäsenet" (First Surname), "Kaupunginhallituksen jäsenet" and "Muut osallistujat";
- votes: the Käsittely prose states the voting proposal and the counts ("Äänestyksessä annettiin
  61 jaa-ääntä ja 6 ei-ääntä"; boards add surnames in brackets); the per-member list is an
  attachment "Äänestysraportti …", one block per vote: "Vote name: JAA=… EI=…", "Agenda name:
  § n …", "Vote start: d.m.yyyy …", totals, group totals, then "Individual Voting Results" with
  "First Last party" lines under JAA / EI / Tyhjää.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..htmlblocks import clean
from ..models import Attachment, Choice, Motion, MotionKind, Outcome, PersonRef, Section, SectionType
from ..pdf import join_lines
from ..people import normalize_name
from ..text import strip_pii
from .dynasty import decode  # noqa: F401  (same charset quirks: ISO-8859-1 pages, UTF-8 PDFs)
from .votes_cloudmeeting import NUMBER_WORDS, PdfVote, ProseVote, _is_genitive

BASE = "https://paatokset.vantaa.fi"
DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
TIME = re.compile(r"(\d{1,2})[:.](\d{2})")
MEETING_HREF = re.compile(r"(pk|epj)_asil_tweb\.htm\?bid=(\d+)")
DOC_HREF = re.compile(r"fileshow\?doctype=\d+&docid=(\d+)")
# "… / PT", "…/PT (kvalt)", "… / TeA": the presenter's initials on board agendas
INITIALS_TAIL = re.compile(r"\s*/\s*[A-ZÅÄÖ][A-Za-zÅÄÖåäö]{1,3}(?:\s*\([a-zåäö]+\))?\s*$")


def parse_date(text: str) -> dt.date | None:
    m = DATE.search(text)
    return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _hhmm(h: str, m: str) -> str:
    return f"{int(h):02d}:{m}"


# -- bodies and listings ------------------------------------------------------------------


def parse_bodies(html: str) -> dict[str, str]:
    """Kirjaamo id → body name, from the first dropdown of the minutes search page."""
    tree = HTMLParser(html)
    select = tree.css_first("select")
    out: dict[str, str] = {}
    if select is None:
        return out
    for opt in select.css("option"):
        value = (opt.attributes.get("value") or "").strip()
        name = clean(opt.text(deep=True))
        if value and name:
            out[value] = name
    return out


@dataclass
class MeetingRow:
    bid: str
    date: dt.date
    start_time: str | None
    url: str
    minutes: bool


def parse_meeting_list(html: str, base: str = BASE) -> list[MeetingRow]:
    rows = []
    for a in HTMLParser(html).css("a"):
        href = a.attributes.get("href") or ""
        m = MEETING_HREF.search(href)
        text = clean(a.text(deep=True))
        date = parse_date(text)
        if not m or date is None:
            continue
        t = TIME.search(text[DATE.search(text).end() :])
        rows.append(
            MeetingRow(
                bid=m.group(2),
                date=date,
                start_time=_hhmm(*t.groups()) if t else None,
                url=urljoin(base + "/ktwebscr/", href),
                minutes=m.group(1) == "pk",
            )
        )
    return rows


@dataclass
class ItemRow:
    ordinal: int
    pykala: int | None
    title: str
    url: str | None  # None when the row has no document link (confidential)
    docid: str | None
    attachments_url: str | None


@dataclass
class MeetingPage:
    compiled_pdf: str | None = None
    cover_pdf: str | None = None
    rows: list[ItemRow] = field(default_factory=list)


def clean_title(title: str) -> str:
    return INITIALS_TAIL.sub("", clean(title)).strip()


COVER_ROW = re.compile(
    r"kansilehti|försättsblad|läsnäolijat|läsnäolevat|närvarande|^osallistujat\b", re.IGNORECASE
)


def parse_meeting(html: str, base: str = BASE) -> MeetingPage:
    page = MeetingPage()
    ordinal = 0
    for tr in HTMLParser(html).css("tr"):
        cells = tr.css("td")
        if not cells:
            continue
        first = clean(cells[0].text(deep=True))
        links = [(a, a.attributes.get("href") or "") for a in tr.css("a")]
        docs = [(a, h) for a, h in links if DOC_HREF.search(h)]
        if len(cells) == 1:
            if first.startswith("Kooste") and docs:
                page.compiled_pdf = urljoin(base + "/ktwebscr/", docs[0][1])
            continue
        title_cell = cells[1]
        title = clean(title_cell.text(deep=True))
        doc = next(((a, h) for a, h in docs if a.parent is not None and a in title_cell.css("a")), None)
        doc_href = doc[1] if doc else (docs[0][1] if docs else None)
        url = urljoin(base + "/ktwebscr/", doc_href) if doc_href else None
        if not re.fullmatch(r"\d+", first):
            # Rows without § are the cover page and the appeal instructions; not items (§7.4).
            if url and re.search(
                r"kansilehti|försättsblad|läsnäolijat|närvarande|^osallistujat\b", title, re.IGNORECASE
            ):
                page.cover_pdf = url
            continue
        ordinal += 1
        attn = next((h for _, h in links if "attn_tweb" in h), None)
        page.rows.append(
            ItemRow(
                ordinal=ordinal,
                pykala=int(first),
                title=clean_title(title),
                url=url,
                docid=DOC_HREF.search(doc_href).group(1) if doc_href else None,
                attachments_url=urljoin(base + "/ktwebscr/", attn) if attn else None,
            )
        )
    return page


def parse_attachments(html: str, base: str = BASE) -> list[Attachment]:
    out = []
    for a in HTMLParser(html).css("td a"):
        href = a.attributes.get("href") or ""
        title = clean(a.text(deep=True))
        if DOC_HREF.search(href) and title:
            out.append(Attachment(title=title, url=urljoin(base + "/ktwebscr/", href)))
    return out


def html_lines(html: str) -> list[str]:
    """Text lines of an item served as HTML instead of PDF."""
    tree = HTMLParser(html)
    for tag in ("script", "style", "header", "nav", "footer"):
        for node in tree.css(tag):
            node.decompose()
    root = tree.css_first("#content") or tree.body
    text = root.text(deep=True, separator="\n") if root is not None else ""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


# -- cover page ---------------------------------------------------------------------------

# "Aika 21.9.2026 klo 18.05–23.18", "Aika 8.6.2026, klo 13.05–17.26", "Aika 17.11.2025 klo 13.00-
# 18.11.2025 klo 0.22", Swedish bodies "Tid Tisdag 09.06.2026, kl. 17.05-19.33", "Tid 10.06.2026 17:00-18:38"
_KLO = r",?\s+(?:(?:klo|kl\.)\s+)?"
SESSION = re.compile(
    rf"^(?:Aika|Tid)\s+(?:[A-Za-zåäö]+\s+)?(\d{{1,2}}\.\d{{1,2}}\.\d{{4}}){_KLO}(\d{{1,2}})[.:](\d{{2}})"
    rf"(?:\s*[–-]\s*(?:\d{{1,2}}\.\d{{1,2}}\.\d{{4}}{_KLO})?(\d{{1,2}})[.:](\d{{2}}))?"
)
PLACE = re.compile(r"^(?:Paikka|Plats)\s+(.+)$")
_PARTICLE = r"(?:(?:el|af|von|de|van)\s+)"
_WORD = rf"{_PARTICLE}?(?!(?:X|[IV]+)(?:[\s)]|$))[A-ZÅÄÖ][\wÅÄÖåäö'’-]*"
_NAME = rf"{_WORD}(?:\s+{_WORD})*"
_MARK = r"(?P<mark>[xX]|-)(?=[\s)]|$)"
# A note in brackets after the mark: "(klo 18.05-21.03 § 1-8)", or cut by the line end or the
# next column's entry: "(pj § 1-6, 13.00- Lahti Timo x" (the rest of the note is on the next line).
NOTE = rf"\([^()]*?(?:\)|(?=\s{_NAME}\s(?:[xX]|-)(?:\s|$))|$)"
# "Kaukola Ulla, puheenjohtaja X", "Kasonen Mika, I varapuheenjohtaja X", "Pietelin Anna, x"; the
# role is lower case, so an unmarked name before the entry does not read as one.
ENTRY = re.compile(
    rf"(?P<name>{_NAME})(?:[,.]\s*(?P<role>[IV]+(?:\s+[a-zåäö][^()A-ZÅÄÖ]*?)?|[a-zåäö][^()A-ZÅÄÖ]*?)?)?\s+{_MARK}"
    rf"(?:\s*(?P<note>{NOTE}))?"
)
# "Muut osallistujat" is one column, so its roles may name an organisation: "Niemistö Jussi,
# tutkimusjohtaja, CBRE Commercial Real X"
# the rest of a wrapped role on the line below: "Kasonen Mika, I x Forsblom-Prittinen Frida" /
# "varapuheenjohtaja"; not a note ("klo 17.00-17.21, § 1-9;")
ROLE_REST = re.compile(r"^(?!klo\b)[a-zåäö][^()A-ZÅÄÖ\d§]*$")
ONE_COLUMN = re.compile(rf"^(?P<name>{_NAME})(?:[,.]\s*(?P<role>.*?))?\s+{_MARK}(?:\s*(?P<note>{NOTE}))?")
GROUPS = [
    (re.compile(r"^(?:Jäsenet\s+(?:Läsnä|Varajäsenet)|Medlemmar\s+Närvarande)"), "jäsen"),
    (re.compile(r"^Varajäsenet\s+Läsnä"), "varajäsen"),
    (
        re.compile(r"^Kaupunginhallituksen (?:jäsenet|edustaja)\b|^Stadsstyrelsens\b"),
        "kaupunginhallituksen jäsen",
    ),
    (re.compile(r"^Nuorisovaltuuston\b|^Ungdomsfullmäktiges\b"), "nuorisovaltuuston edustaja"),
    (re.compile(r"^(?:Muut osallistujat|Övriga deltagare)\b"), "muu osallistuja"),
]
DEPUTY_COLUMN = re.compile(r"Varajäsenet|varaedustaja|[Ee]rsättare")
COVER_END = re.compile(
    r"^(Kokouksen laillisuus|Allekirjoitukset|Pöytäkirjan tarkastus|Käsitellyt asiat|Sammanträdets laglighet"
    r"|Underskrifter)"
)


@dataclass
class Participant:
    name: str
    role: str
    present: bool
    note: str | None = None


@dataclass
class Cover:
    date: dt.date | None = None
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = None
    participants: list[Participant] = field(default_factory=list)


def _note(note: str | None) -> str | None:
    if not note:
        return None
    if not note.endswith(")"):  # cut by the line end: drop an unmarked name from the next column
        note = re.split(r"\s(?=(?:el\s)?[A-ZÅÄÖ][a-zåäö])", note, maxsplit=1)[0]
    return note.strip("() ") or None


# Rauma's cover PDF: "KOKOUSAIKA 20.1.2025 klo 15.30-17.18, 17.24-19.23", "KOKOUSPAIKKA ...", then
# "OSALLISTUJAT" with one person a line, "Firstname Lastname, role[, poissa][, 3)]", no x/- marks:
# everyone is present unless "poissa". Footnotes "1) paikalla kokouksessa klo 15.30-18.48" are a
# second column that the text layer runs onto the same lines. The list ends at ALLEKIRJOITUKSET.
OSALLISTUJAT = re.compile(r"^OSALLISTUJAT\b\s*")
KOKOUSAIKA = re.compile(
    r"^KOKOUSAIKA\s+(\d{1,2}\.\d{1,2}\.\d{4})\s+(?:klo\s+)?(\d{1,2})[.:](\d{2})(?:.*[–-]\s*(\d{1,2})[.:](\d{2}))?"
)
KOKOUSPAIKKA = re.compile(r"^KOKOUSPAIKKA\s+(.+)$")
FOOTNOTE_TEXT = re.compile(r"(?:^|\s)(\d{1,2})\)\s+((?:paikalla|saapui|poistui|oli|läsnä)\b.*)$")
FOOTNOTE_MARKS = re.compile(r"(?:,?\s*\d{1,2}\))+\s*$")
OSALLISTUJA = re.compile(r"^(?P<name>[A-ZÅÄÖ][^,\d]*?)\s*,\s*(?P<role>[^,]+?)(?:\s*,\s*(?P<absent>poissa))?$")


def is_osallistujat_cover(lines: list[str]) -> bool:
    return any(OSALLISTUJAT.match(ln.strip()) for ln in lines)


def parse_cover_osallistujat(lines: list[str]) -> Cover:
    cover = Cover()
    notes: dict[str, str] = {}
    people: list[tuple[Participant, list[str]]] = []
    inside = False
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if m := KOKOUSAIKA.match(line):
            cover.date = parse_date(m.group(1))
            cover.start_time = _hhmm(m.group(2), m.group(3))
            cover.end_time = _hhmm(m.group(4), m.group(5)) if m.group(4) else None
            continue
        if (m := KOKOUSPAIKKA.match(line)) and cover.location is None:
            cover.location = m.group(1)
            continue
        if m := OSALLISTUJAT.match(line):
            inside, line = True, line[m.end() :]
        elif not inside:
            continue
        if re.match(r"^(?:ALLEKIRJOITUKSET|KÄSITELTÄVÄT ASIAT|PÖYTÄKIRJAN)\b", line):
            break
        if m := FOOTNOTE_TEXT.search(line):
            notes[m.group(1)] = m.group(2).strip()
            line = line[: m.start()].strip()
        marks = []
        if m := FOOTNOTE_MARKS.search(line):
            marks = re.findall(r"\d{1,2}", m.group(0))
            line = line[: m.start()].strip(" ,")
        if not (m := OSALLISTUJA.match(line)):
            continue
        # printed "Firstname Lastname": turn it round to "Lastname Firstname" as on other covers
        tokens = m.group("name").split()
        name = " ".join([tokens[-1], *tokens[:-1]])
        p = Participant(name=name, role=m.group("role").strip(), present=not m.group("absent"))
        people.append((p, marks))
    for p, marks in people:
        p.note = "; ".join(notes[k] for k in marks if k in notes) or None
        cover.participants.append(p)
    return cover


# Akaa and Valkeakoski cover PDFs: unmarked blocks labelled at the left, "Päätöksentekijät",
# "Muut osallistujat", "Poissa [olleet]". An entry is "Surname First role [times]" with no comma
# (Akaa; a role left alone on a line belongs to the bare name on the next), "Puheenjohtaja Surname
# First", or a comma list after "Jäsenet:" / "Varavaltuutetut:" that wraps names across lines
# (Valkeakoski).
BLOCK_LABELS = [
    (re.compile(r"^Päätöksentekijät\b\s*"), "jäsen", True),
    (re.compile(r"^Muut osallistujat\b\s*"), "muu osallistuja", True),
    (re.compile(r"^Poissa(?: olleet)?\b\s*"), "jäsen", False),
]
BLOCK_END = re.compile(r"^(?:Laillisuus|Pöytäkirjan|Allekirjoitukset|Käsitellyt asiat|Asiat\b)")
BLOCK_LIST = re.compile(r"^(?P<label>Jäsenet|Varavaltuutetut|Varajäsenet):\s*")
BLOCK_TIME = re.compile(
    r"^Kokousaika\s+(?:[a-zåäö]{2}\s+)?(\d{1,2}\.\d{1,2}\.\d{4}),?\s+(?:klo\s+)?(\d{1,2})[.:](\d{2})"
    r"(?:.*[–-]\s*(\d{1,2})[.:](\d{2}))?"
)
_SURNAME_FIRST = r"(?:[A-ZÅÄÖ][\wÅÄÖåäö'’-]*\s+){1,2}?[A-ZÅÄÖ][\wÅÄÖåäö'’-]*"
BLOCK_ENTRY = re.compile(
    rf"^(?P<name>{_SURNAME_FIRST})(?:\s+(?P<role>(?:[IV]+\s+)?[a-zåäö][^\d]*?))?"
    r"(?:\s+(?P<note>\(?(?:klo\.?\s*)?\d{1,2}[.:]\d{2}.*))?,?$"
)
BLOCK_ROLE_FIRST = re.compile(
    rf"^(?P<role>(?:[IV]+\s+)?(?:Vara)?[Pp]uheenjohtaja)\s+(?P<name>{_SURNAME_FIRST})$"
)
BLOCK_BARE_ROLE = re.compile(r"^(?:[IV]+\s+)?[a-zåäö][a-zåäö -]*$")


def is_block_cover(lines: list[str]) -> bool:
    return any(re.match(r"^Päätöksentekijät\s+\S", ln.strip()) for ln in lines)


def _list_entries(text: str, role: str, present: bool) -> list[Participant]:
    out = []
    for part in text.split(","):
        part = part.strip()
        note = None
        if b := re.search(r"\s*\(([^)]*)\)\s*$", part):
            part, note = part[: b.start()], b.group(1).strip()
        if re.fullmatch(_SURNAME_FIRST, part):
            out.append(Participant(name=part, role=role, present=present, note=note))
    return out


def parse_cover_blocks(lines: list[str]) -> Cover:
    cover = Cover()
    group, present = None, True
    listing: tuple[str, list[str]] | None = None  # a comma list being gathered: role, lines
    pending_role: str | None = None

    def flush() -> None:
        nonlocal listing
        if listing:
            cover.participants.extend(_list_entries(" ".join(listing[1]), listing[0], present))
            listing = None

    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if m := BLOCK_TIME.match(line):
            cover.date = parse_date(m.group(1))
            cover.start_time = _hhmm(m.group(2), m.group(3))
            cover.end_time = _hhmm(m.group(4), m.group(5)) if m.group(4) else None
            continue
        if (m := re.match(r"^Kokouspaikka\s+(.+)$", line)) and cover.location is None:
            cover.location = m.group(1)
            continue
        if BLOCK_END.match(line):
            if cover.participants or listing:
                break
            continue
        for rx, g, p in BLOCK_LABELS:
            if m := rx.match(line):
                flush()
                group, present, line = g, p, line[m.end() :]
                break
        if group is None or not line:
            continue
        if m := BLOCK_LIST.match(line):
            flush()
            listing = ("jäsen" if m.group("label") == "Jäsenet" else "varajäsen", [line[m.end() :]])
            continue
        if listing:
            listing[1].append(line)
            continue
        if not present:  # "Fuss Jouni," one a line
            line = line.rstrip(",")
        if BLOCK_BARE_ROLE.match(line):
            pending_role = line
            continue
        if m := BLOCK_ROLE_FIRST.match(line):
            role = m.group("role")
            role = role if re.match(r"[IV]+\s", role) else role.lower()
            cover.participants.append(Participant(name=m.group("name"), role=role, present=present))
            continue
        if re.match(r"^\(?(?:klo\.?\s*)?\d", line):  # "18.00-21.22, 21.23-21.37": the note of the last one
            if cover.participants and cover.participants[-1].note is None:
                cover.participants[-1].note = line.strip("() ")
            continue
        if not (m := BLOCK_ENTRY.match(line)):
            continue
        role, _, said = (m.group("role") or "").partition(", ")  # "varaedustaja, saapui klo. 11.33"
        role = role.strip(" ,") or pending_role or group
        pending_role = None
        note = " ".join(filter(None, [said.strip(), (m.group("note") or "").strip("() ,")])) or None
        cover.participants.append(Participant(name=m.group("name"), role=role, present=present, note=note))
    flush()
    return cover


# Lieto: a "Surname First Role" table under "Jäsenet Tehtävä", "Varajäsenet" and "Muut osallistujat
# Tehtävä"; roles are capitalised ("Jäsen", "I varapuheenjohtaja"), the page header repeats.
TABLE_HEAD = re.compile(
    r"^(?P<label>Jäsenet|Varajäsenet|Muut osallistujat|Poissa(?:olleet| olleet)?)(?:\s+Tehtävä)?$"
)
TABLE_GROUPS = {
    "jäsenet": ("jäsen", True),
    "varajäsenet": ("varajäsen", True),
    "muut osallistujat": ("muu osallistuja", True),
}
TABLE_ROW = re.compile(
    r"^(?P<name>[A-ZÅÄÖ][\wÅÄÖåäö'’-]+\s+[A-ZÅÄÖ][\wÅÄÖåäö'’-]+)"
    r"(?:\s+(?P<role>(?:[IV]+\s+)?[A-ZÅÄÖa-zåäö][^\d]*?))?(?:\s+(?P<note>\d.*))?$"
)


def is_table_cover(lines: list[str]) -> bool:
    return any(re.fullmatch(r"Jäsenet\s+Tehtävä", ln.strip()) for ln in lines)


def parse_cover_table(lines: list[str]) -> Cover:
    cover = Cover()
    group: tuple[str, bool] | None = None
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or PAGE_HEADER.match(line) or re.fullmatch(r"[A-ZÅÄÖ ]+(?:KAUPUNKI|KUNTA)", line):
            continue
        if m := re.match(
            r"^Aika\s+(?:(\d{1,2}\.\d{1,2}\.\d{4})\s+)?(?:klo\s+)?(\d{1,2})[.:](\d{2})"
            r"(?:\s*[–-]\s*(\d{1,2})[.:](\d{2}))?",
            line,
        ):
            cover.date = parse_date(m.group(1)) if m.group(1) else None
            cover.start_time = _hhmm(m.group(2), m.group(3))
            cover.end_time = _hhmm(m.group(4), m.group(5)) if m.group(4) else None
            continue
        if (m := PLACE.match(line)) and cover.location is None:
            cover.location = m.group(1)
            continue
        if m := TABLE_HEAD.match(line):
            label = m.group("label").lower()
            group = TABLE_GROUPS.get(label, ("jäsen", False))
            continue
        if BLOCK_END.match(line) or COVER_END.match(line):
            if cover.participants:
                break
            continue
        if group is None or not (m := TABLE_ROW.match(line)):
            continue
        role = (m.group("role") or "").strip()
        if role and not re.match(r"[IV]+\s", role):
            role = role[0].lower() + role[1:]
        present = group[1] and role.lower() != "poissa"
        if role.lower() == "poissa":
            role = ""
        cover.participants.append(
            Participant(name=m.group("name"), role=role or group[0], present=present, note=m.group("note"))
        )
    return cover


def parse_cover(lines: list[str]) -> Cover:
    if is_osallistujat_cover(lines):
        return parse_cover_osallistujat(lines)
    if is_table_cover(lines):
        return parse_cover_table(lines)
    if is_block_cover(lines):
        return parse_cover_blocks(lines)
    cover = Cover()
    group: str | None = None
    deputies = False
    wrapped: tuple[Participant, str] | None = None  # a role cut after "I" or a comma goes on below
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or re.fullmatch(r"Nro \d+/\d{4}", line):
            continue
        if wrapped and ROLE_REST.match(line):
            wrapped[0].role += wrapped[1] + line
            wrapped = None
            continue
        wrapped = None
        if m := SESSION.match(line):
            cover.date = parse_date(m.group(1))
            cover.start_time = _hhmm(m.group(2), m.group(3))
            cover.end_time = _hhmm(m.group(4), m.group(5)) if m.group(4) else None
            continue
        if (m := PLACE.match(line)) and cover.location is None:
            cover.location = m.group(1)
            continue
        if COVER_END.match(line):
            if cover.participants:
                break
            continue
        hit = next((role for rx, role in GROUPS if rx.match(line)), None)
        if hit:
            group = hit
            # "Jäsenet Läsnä Varajäsenet Läsnä": the second column holds the deputies
            deputies = bool(DEPUTY_COLUMN.search(line[1:]))
            continue
        if group is None or re.match(r"^[\d§]", line):  # "22.10 § 1-9)": the rest of a note
            continue
        found = ONE_COLUMN.match(line) if group == "muu osallistuja" else None
        for m in [found] if found else ENTRY.finditer(line):
            name = m.group("name").strip()
            second = m.start() > 0
            if len(name.split()) > 3:  # an unmarked name from the first column ran into this one
                name, second = " ".join(name.split()[-2:]), True
            if not re.match(r"^[A-ZÅÄÖa-zåäö]", name) or name.lower() in ("läsnä", "jäsenet"):
                continue
            raw_role = (m.group("role") or "").strip()
            role = raw_role.strip(" ,") or ("varajäsen" if deputies and second else group)
            note = m.group("note")
            p = Participant(name=name, role=role, present=m.group("mark") in "xX", note=_note(note))
            cover.participants.append(p)
            if not second and re.search(r"(?:^[IV]+|,)$", raw_role):
                wrapped = p, ", " if raw_role.endswith(",") else " "
    return cover


# Some installs (Hämeenlinna) have no cover PDF: a "Läsnäolijat" row links an HTML page with one
# <h2> heading per field and the values in the next <p>, one per <br>: "Aika" "9.6.2025 18:00 -
# 20:27", "Paikka", "Päätöksentekijät" (present, no x/- mark: "Surname First[, 1.
# varapuheenjohtaja]", deputies "Name (kokoomuksen 1. varavaltuutettu)", a bare note "§ 72-86 klo
# 18.00-19.02"), "Muut osallistujat" ("Name, kaupunginjohtaja"), "Poissa" (absent members), then
# Puheenjohtaja, Pöytäkirjanpitäjä and so on, which are not attendance.
SECTION_GROUPS = {
    "päätöksentekijät": ("jäsen", True),
    "beslutsfattare": ("jäsen", True),
    "muut osallistujat": ("muu osallistuja", True),
    "övriga deltagare": ("muu osallistuja", True),
    "poissa": ("jäsen", False),
    "frånvarande": ("jäsen", False),
    # Raasepori: "Närvarande" with Ordinarie / Ersättare / Frånvarande / Övriga närvarande
    "ordinarie": ("jäsen", True),
    "ersättare": ("varajäsen", True),
    "övriga närvarande": ("muu osallistuja", True),
    # other installs: Kerava "Osallistujat", Nokia "Jäsenet", Pirkkala "Läsnäolijat", Kauhajoki
    # "Saapuvilla olleet jäsenet" / "Varavaltuutetut" / "Poissa olleet", Muurame "Muut läsnäolijat"
    "osallistujat": ("jäsen", True),
    "jäsenet": ("jäsen", True),
    "läsnäolijat": ("jäsen", True),
    "saapuvilla olleet jäsenet": ("jäsen", True),
    "saapuvilla olleet": ("jäsen", True),
    "varajäsenet": ("varajäsen", True),
    "varavaltuutetut": ("varajäsen", True),
    "poissa olleet": ("jäsen", False),
    "poissaolleet": ("jäsen", False),
    "muut läsnäolijat": ("muu osallistuja", True),
}
SECTION_TIME_HEADINGS = ("aika", "tid", "kokousaika", "sammanträdestid")
SECTION_PLACE_HEADINGS = ("paikka", "plats", "kokouspaikka", "sammanträdesplats")
SECTION_ENTRY = re.compile(
    r"^(?P<name>[^,(§]+?)(?:,\s*(?P<role>[^(§]+?))?\s*(?:\((?P<bracket>[^)]*)\))?"
    r"\s*(?P<note>(?:§|klo\b|kl\.).*)?$"
)
SECTION_TIME = re.compile(
    r"(\d{1,2}\.\d{1,2}\.\d{4})(?:,?\s*(?:klo|kello|kl\.)?\s*(\d{1,2})[.:](\d{2}))?"
    r"(?:\s*[–-]\s*(?:\d{1,2}\.\d{1,2}\.\d{4}\s*)?(?:klo\s*)?(\d{1,2})[.:](\d{2}))?"
)


def is_section_cover(html: str) -> bool:
    """An HTML attendance page: an <h2> that names a group of attendees."""
    for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", html, re.IGNORECASE | re.DOTALL):
        if clean(re.sub(r"<[^>]+>", "", m.group(1))).strip("{} ").lower() in SECTION_GROUPS:
            return True
    return False


# "(KOK) Enjala Terhi, puheenjohtaja" (Kerava prints the party first)
SECTION_PARTY = re.compile(r"^\([A-ZÅÄÖ][A-ZÅÄÖa-zåäö.]{0,7}\)\s*")
# "Puheenjohtaja, Hautala Lasse", "Valtuutettu, Björkman Petri" (Kauhajoki prints the role first)
SECTION_ROLE_FIRST = re.compile(
    r"^(?P<role>(?:(?:[IV]+|\d\.)\s+)?(?:vara)?puheenjohtaja|(?:vara)?valtuutettu|(?:vara)?jäsen)\s*,\s*"
    r"(?P<name>[A-ZÅÄÖ].*)$",
    re.IGNORECASE,
)
# a trailing ", poissa" (absent) or ", varajäsen" (a deputy): Muurame, Pirkkala's table cells
SECTION_TAIL = re.compile(r"\s*,\s*(?P<tail>poissa|varajäsen|varavaltuutettu)\s*$", re.IGNORECASE)
_LIST_NAME = re.compile(r"^[A-ZÅÄÖ][\wÅÄÖåäö'’-]+(?:\s+[A-ZÅÄÖ][\wÅÄÖåäö'’-]+){1,2}$")


def _section_entries(value: str) -> list[str]:
    """A comma list of names, "Kiukkonen Olli, Mäki Erkki, Soini Pekka", is one entry a name."""
    parts = [p.strip() for p in value.split(",")]
    if len(parts) > 1 and all(_LIST_NAME.match(p) for p in parts):
        return parts
    return [value]


def _section_values(node) -> list[str]:
    """One value per <br> line, or per table row: Ilmajoki puts a "name | role" table in the <p>,
    one row a person, which reads as "name, role"."""
    rows = node.css("tr")
    if rows:
        out = []
        for tr in rows:
            cells = [clean(td.text(deep=True)) for td in tr.css("td, th")]
            cells = [c for c in cells if c]
            if cells:
                out.append(", ".join(cells))
        return out
    # Muurame: "Jarkko Määttänen\t\tkunnanjohtaja" in "Muut läsnäolijat"
    lines = [re.sub(r"\s*\t+\s*", ", ", v.strip()) for v in node.text(deep=True, separator="\n").splitlines()]
    return [clean(v) for v in lines if clean(v)]


def parse_cover_sections(html: str) -> Cover:
    cover = Cover()
    for h2 in HTMLParser(html).css("h2"):
        heading = clean(h2.text(deep=True)).strip("{} ").lower()  # "{Sammanträdesplats}"
        # the <p> under the heading; a table in it closes the <p>, so read up to the next <h2>
        values: list[str] = []
        node = h2.next
        while node is not None and node.tag not in ("h2", "h1"):
            if node.tag != "-text":
                values += _section_values(node)
                if values and node.tag == "p" and not node.css("table"):
                    break
            node = node.next
        if heading in SECTION_TIME_HEADINGS and values and (m := SECTION_TIME.search(values[0])):
            cover.date = parse_date(m.group(1))
            cover.start_time = _hhmm(m.group(2), m.group(3)) if m.group(2) else None
            cover.end_time = _hhmm(m.group(4), m.group(5)) if m.group(4) else None
        elif heading in SECTION_PLACE_HEADINGS and values:
            cover.location = values[0]
        elif heading in SECTION_GROUPS:
            group, present = SECTION_GROUPS[heading]
            for value in (e for v in values for e in _section_entries(SECTION_PARTY.sub("", v))):
                here, role_first = present, None
                while t := SECTION_TAIL.search(value):
                    value = value[: t.start()]
                    if t.group("tail").lower() == "poissa":
                        here = False
                    else:
                        role_first = t.group("tail").lower()
                if f := SECTION_ROLE_FIRST.match(value):
                    value, role_first = f.group("name"), f.group("role")
                    role_first = role_first if re.match(r"[IV]+\s", role_first) else role_first.lower()
                if ":" in value or not (m := SECTION_ENTRY.match(value)):  # "Liite: Nimenhuutoluettelo"
                    continue
                name = m.group("name").strip()
                if not re.match(r"^[A-ZÅÄÖ]", name) or name.lower() == "poissa":
                    continue
                printed_role, bracket = m.group("role"), m.group("bracket")
                note = (m.group("note") or "").strip() or None
                if printed_role and re.match(r"\d{1,2}[.:]\d{2}\b", printed_role):  # "17.12 alkaen (§ 117)"
                    note = " ".join(
                        filter(None, [printed_role.strip(), f"({bracket})" if bracket else None, note])
                    )
                    printed_role = bracket = None
                role = (printed_role or bracket or "").strip(" ,") or role_first or group
                if printed_role and bracket:
                    note = " ".join(filter(None, [bracket.strip(), note]))
                cover.participants.append(Participant(name=name, role=role, present=here, note=note))
    return cover


# -- item document ------------------------------------------------------------------------

DIARY = re.compile(r"^[A-ZÅÄÖ]{1,4}/\d+/[\d.]+/\d{4}$")
INITIALS = re.compile(r"^[A-ZÅÄÖ][A-Za-zÅÄÖåäö]{0,3}(?:/[A-ZÅÄÖ][A-Za-zÅÄÖåäö]{0,3})*$")
BODY_WORD = r"(?:valtuusto|hallitus|lautakun\w*|jaosto|johtokunta|toimikunta|neuvosto)"
_BLOCK_BODY = (
    rf"(?P<body>(?=[A-ZÅÄÖ])(?:[\wÅÄÖåäö-]+\s+){{0,5}}?[\wÅÄÖåäö-]*?(?i:{BODY_WORD})"
    r"[\wåäö]*(?:\s+[\wåäö-]+)?)"
)
# "Kaupunginhallitus 9.6.2025 § 209", "Valtuusto 19.5.2025 § 55"; Rauma: "Kaupunginhallitus 273 § 22.6.2026"
BLOCK = re.compile(
    rf"^{_BLOCK_BODY}\s+(?:(?P<date>\d{{1,2}}\.\d{{1,2}}\.\d{{4}})\s+§\s*(?P<n>\d+)"
    rf"|(?P<n2>\d+)\s*§\s+(?P<date2>\d{{1,2}}\.\d{{1,2}}\.\d{{4}}))$"
)
PROPOSAL = re.compile(r"^(?:[\wÅÄÖåäö.-]+\s+){0,5}esitys\s*:$|^Esitys\s*:$", re.IGNORECASE)
HEADINGS = {
    "käsittely": SectionType.deliberation,
    "päätös": SectionType.decision,
    "päätösehdotus": SectionType.proposal,
}
ATTACHMENTS = re.compile(r"^(Liite|Liitteet|Oheismateriaali)\s*:", re.IGNORECASE)
END = re.compile(r"^(Muutoksenhakuohje|Lisätiedot|Lisätietoja|Tiedoksi)\b", re.IGNORECASE)
RULE = re.compile(r"^[_-]{3,}$")
# a running page header in the middle of an item: "RAUMAN KAUPUNKI Kokouspäivä" and then
# "Kaupunginvaltuusto 31.8.2026"
PAGE_HEADER = re.compile(r"^[A-ZÅÄÖ]{3,}(?:\s+[A-ZÅÄÖ]{3,})*\s+(?:KAUPUNKI|KUNTA)\b")
PAGE_HEADER_DATE = re.compile(r"^[A-ZÅÄÖ][\wåäö -]*\s+\d{1,2}\.\d{1,2}\.\d{4}$")
STATEMENT = re.compile(r"^Merkittiin,?\s+että\b.*(pöytäkirjalausum|eriävän mielipiteen)", re.IGNORECASE)


@dataclass
class Block:
    body: str
    date: dt.date
    pykala: int
    lines: list[str] = field(default_factory=list)

    @property
    def header(self) -> str:
        return f"{self.body} {self.date.day}.{self.date.month}.{self.date.year} § {self.pykala}"


@dataclass
class ItemDoc:
    case_number: str | None = None
    background: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    attachment_titles: list[str] = field(default_factory=list)


def parse_item_lines(lines: list[str], title: str | None = None) -> ItemDoc:
    lines = [ln.rstrip() for ln in lines if not ln.startswith("--- page ")]
    lines = [ln for ln in lines if ln.strip()]
    kept: list[str] = []
    for i, ln in enumerate(lines):
        if i > 0 and PAGE_HEADER.match(ln.strip()):
            continue
        if kept and i > 0 and PAGE_HEADER.match(lines[i - 1].strip()) and PAGE_HEADER_DATE.match(ln.strip()):
            continue
        kept.append(ln)
    lines = kept
    doc = ItemDoc()
    # title, then the diary number and the preparers' initials
    start = 0
    for i, ln in enumerate(lines[:6]):
        if DIARY.match(ln.strip()):
            doc.case_number = ln.strip()
            start = i + 1
            if start < len(lines) and INITIALS.match(lines[start].strip()):
                start += 1
            break
    else:
        start = len(_title_prefix(lines, title))
    cur: list[str] = doc.background
    in_attachments = False
    for ln in lines[start:]:
        s = ln.strip()
        if END.match(s):
            break
        if m := BLOCK.match(s):
            date = parse_date(m.group("date") or m.group("date2"))
            assert date is not None
            n = int(m.group("n") or m.group("n2"))
            doc.blocks.append(Block(body=m.group("body"), date=date, pykala=n))
            cur = doc.blocks[-1].lines
            in_attachments = False
            continue
        if ATTACHMENTS.match(s):
            in_attachments = True
            rest = ATTACHMENTS.sub("", s).strip(" -")
            if rest:
                doc.attachment_titles.append(rest)
            continue
        if in_attachments and _heading(s):
            in_attachments = False
        if in_attachments:
            if s.startswith("-") or not doc.attachment_titles:
                doc.attachment_titles.append(s.lstrip("- ").strip())
            else:
                doc.attachment_titles[-1] += " " + s
            continue
        cur.append(ln)
    return doc


# Items some installs (Hämeenlinna, Kerava, Raasepori) serve as HTML: a <header> with "{Body}<br>
# d.m.yyyy § n[<br>diary number]", an <h1> title, then one <h2> per part with the text in the next
# <p>. The meeting's own handling comes first; earlier handlings follow, each opened by a <p>
# "{Body} d.m.yyyy § n" (Raasepori puts "Beslutshistorik" before them). Swedish installs use
# Förslag / Beslutets behandling / Beslut and leave template headings such as "{Ärendenummer}:".
HTML_PARTS = {
    "päätös": SectionType.decision,
    "beslut": SectionType.decision,
    "päätösehdotus": SectionType.proposal,
    "ehdotus": SectionType.proposal,
    "förslag": SectionType.proposal,
    "beslutsförslag": SectionType.proposal,
    "kokouskäsittely": SectionType.deliberation,
    "käsittely": SectionType.deliberation,
    "behandling": SectionType.deliberation,
    "beslutets behandling": SectionType.deliberation,
    "selostus": SectionType.background,
    "asiateksti": SectionType.background,
    "perustelut": SectionType.background,
    "beredningstext": SectionType.background,
    "beredning": SectionType.background,
}
HTML_ATTACHMENTS = {"liitteet", "liite", "bilagor", "bilaga"}
HTML_HEADINGS = {
    SectionType.decision: "Päätös:",
    SectionType.proposal: "Päätösehdotus:",
    SectionType.deliberation: "Käsittely:",
}
HTML_BLOCK = re.compile(r"^(?P<body>[A-ZÅÄÖ][^§]*?)\s+(?P<date>\d{1,2}\.\d{1,2}\.\d{4})\s*§\s*(?P<n>\d+)$")


def is_html_item(html: str) -> bool:
    """An item page of the <header> + <h2> layout (not a plain page of lines)."""
    return bool(re.search(r"<header\b", html, re.IGNORECASE)) and "<h2" in html.lower()


def _html_part(heading: str) -> SectionType | None:
    key = heading.rstrip(":").strip().lower()
    if key in HTML_PARTS:
        return HTML_PARTS[key]
    if re.search(r"(?:esitys|förslag)$", key):  # "Kaupunginjohtajan esitys", "Stadsdirektörens förslag"
        return SectionType.proposal
    return None


def parse_item_html(html: str) -> ItemDoc:
    tree = HTMLParser(html)
    doc = ItemDoc()
    root = tree.css_first("main") or tree.body
    if root is None:
        return doc
    header = root.css_first("header p") or tree.css_first("header p")
    head = (
        [clean(v) for v in header.text(deep=True, separator="\n").splitlines() if clean(v)] if header else []
    )
    own: Block | None = None
    if len(head) >= 2 and (m := HTML_BLOCK.match(f"{head[0]} {head[1]}")):
        date = parse_date(m.group("date"))
        assert date is not None
        own = Block(body=m.group("body"), date=date, pykala=int(m.group("n")))
        if len(head) > 2 and DIARY.match(head[2]):
            doc.case_number = head[2]
    earlier: list[Block] = []
    cur = own
    part: SectionType | str | None = None  # a SectionType, "attachments", "diary" or None (skipped)
    emitted: SectionType | str | None = None  # the part whose heading line was emitted last
    for node in root.iter():
        if node.tag in ("header", "h1", "div", "br", "-text", "script", "style"):
            continue
        text_lines = [clean(v) for v in node.text(deep=True, separator="\n").splitlines() if clean(v)]
        if node.tag == "h2":
            heading = " ".join(text_lines)
            if "ärendenummer" in heading.lower() or "asianumero" in heading.lower():
                part = "diary"
            elif heading.rstrip(":").strip().lower() in HTML_ATTACHMENTS:
                part = "attachments"
            else:
                part = _html_part(heading)
            emitted = None
            continue
        if not text_lines or all(RULE.match(t) for t in text_lines):
            continue
        whole = " ".join(text_lines)
        if (m := HTML_BLOCK.match(whole)) and len(text_lines) == 1:
            date = parse_date(m.group("date"))
            assert date is not None
            if own and date == own.date and int(m.group("n")) == own.pykala:
                continue  # Kerava repeats the header line
            cur = Block(body=m.group("body"), date=date, pykala=int(m.group("n")))
            earlier.append(cur)
            part = None
            continue
        if part == "diary":
            if DIARY.match(whole) and doc.case_number is None:
                doc.case_number = whole
            continue
        if part == "attachments":
            if cur is own:
                doc.attachment_titles += text_lines
            continue
        if part is None or cur is None:
            continue
        if cur is not own:  # an earlier handling: kept as one history text
            cur.lines += text_lines
        elif part == SectionType.background:
            doc.background += text_lines
        else:
            if emitted != part:  # a <ul> inside a <p> comes out as the next node, same part
                cur.lines.append(HTML_HEADINGS[part])
                emitted = part
            cur.lines += text_lines
    doc.blocks = sorted(earlier, key=lambda b: b.date) + ([own] if own else [])
    return doc


def _title_prefix(lines: list[str], title: str | None) -> list[str]:
    """The leading lines that spell the title (a long title wraps over two or three lines)."""
    if not lines:
        return []
    want = re.sub(r"\s+", " ", INITIALS_TAIL.sub("", title or "")).strip().lower()
    if not want:
        return lines[:1]
    got: list[str] = []
    for ln in lines[:4]:
        nxt = re.sub(r"\s+", " ", " ".join([*got, ln.strip()])).lower()
        nxt = nxt.replace("- ", "-")
        if want.startswith(nxt.rstrip(" -")) or nxt.rstrip(" -") == want:
            got.append(ln.strip())
            if nxt.rstrip(" -") == want:
                break
        else:
            break
    return got or lines[:1]


def end_at_meeting(doc: ItemDoc, date: dt.date, pykala: int | None) -> None:
    """The meeting's own block is the last one (§7.4), unless the document already carries later
    handling: then cut after the block of this date (and §, when known)."""
    for i, b in enumerate(doc.blocks):
        if b.date == date and (pykala is None or b.pykala == pykala):
            del doc.blocks[i + 1 :]
            return


# Rauma prints the heading in a left column, on the same line as the text: "Kokouskäsittely Yleis-
# keskustelun aikana …", "Päätös Päätös: Hyväksyttiin.", "Päätösehdotus Kaupunginhallitus:".
INLINE_HEADING = re.compile(r"^(?P<h>Kokouskäsittely|Päätösehdotus|Päätös)\s+(?P<rest>[A-ZÅÄÖ].*)$")


def _inline_heading(line: str) -> tuple[SectionType, str, str] | None:
    m = INLINE_HEADING.match(line.strip())
    if not m:
        return None
    kind = {
        "kokouskäsittely": SectionType.deliberation,
        "päätösehdotus": SectionType.proposal,
        "päätös": SectionType.decision,
    }[m.group("h").lower()]
    rest = re.sub(r"^Päätös\s*:\s*", "", m.group("rest")) if kind == SectionType.decision else m.group("rest")
    return kind, m.group("h"), rest


def _heading(line: str) -> tuple[SectionType, str] | None:
    s = line.strip()
    if PROPOSAL.match(s):
        return SectionType.proposal, s.rstrip(":").strip()
    key = s.rstrip(":").strip().lower()
    if s.endswith(":") and key in HEADINGS:
        return HEADINGS[key], s.rstrip(":").strip()
    return None


def _text(lines: list[str]) -> str:
    return strip_pii(join_lines([ln for ln in lines if not RULE.match(ln.strip())]).strip())


def block_parts(block: Block) -> list[tuple[SectionType, str, list[str]]]:
    """(type, heading, lines) for the parts of one handling block."""
    parts: list[tuple[SectionType, str, list[str]]] = []
    for ln in block.lines:
        h = _heading(ln)
        if h:
            parts.append((h[0], h[1], []))
        elif inline := _inline_heading(ln):
            parts.append((inline[0], inline[1], [inline[2]]))
        elif parts:
            parts[-1][2].append(ln)
        else:
            parts.append((SectionType.other, "", [ln]))
    return parts


def _split_statements(lines: list[str]) -> tuple[list[str], list[tuple[SectionType, list[str]]]]:
    """Split "Merkittiin, että … jätti … pöytäkirjalausuman / eriävän mielipiteen" paragraphs off a
    decision. A paragraph runs to the next "Merkittiin" line."""
    head: list[str] = []
    out: list[tuple[SectionType, list[str]]] = []
    joined = [re.sub(r"\s+", " ", ln).strip() for ln in lines]
    i = 0
    while i < len(lines):
        # the "Merkittiin" sentence can wrap; look at it with the next line
        probe = " ".join(joined[i : i + 2])
        if joined[i].startswith("Merkittiin") and STATEMENT.match(probe):
            kind = SectionType.dissent if "eriävän" in probe.lower() else SectionType.statement
            out.append((kind, [lines[i]]))
        elif out and not RULE.match(joined[i]):
            if joined[i].startswith("Merkittiin"):
                head.append(lines[i])
            else:
                out[-1][1].append(lines[i])
        else:
            head.append(lines[i])
        i += 1
    return head, out


def item_sections(doc: ItemDoc) -> tuple[list[Section], list[Section], list[str]]:
    """Sections, statements and the meeting's own Käsittely lines (for motions and votes)."""
    sections: list[Section] = []
    statements: list[Section] = []
    if text := _text(doc.background):
        sections.append(Section(type=SectionType.background, text=text))
    deliberation: list[str] = []
    for i, block in enumerate(doc.blocks):
        last = i == len(doc.blocks) - 1
        if not last:
            if text := _text(block.lines):
                sections.append(Section(type=SectionType.history, heading=block.header, text=text))
            continue
        in_case = decided = False
        for kind, heading, lines in block_parts(block):
            # The Käsittely runs to the decision; a changed proposal inside it ("Kaupunginjohtajan
            # muutettu esitys:") is part of it. A proposal after a decision means an earlier
            # body's handling whose header line was missed: only what follows is this meeting's.
            if kind == SectionType.proposal and decided:
                deliberation, decided = [], False
            if kind == SectionType.deliberation:
                in_case = True
            elif kind == SectionType.decision:
                in_case, decided = False, True
            if in_case:
                deliberation += lines
            if kind == SectionType.decision:
                lines, stmts = _split_statements(lines)
                for skind, slines in stmts:
                    if text := _text(slines):
                        statements.append(Section(type=skind, text=text))
            if text := _text(lines):
                sections.append(Section(type=kind, heading=heading or None, text=text))
    if not deliberation and doc.blocks:
        last = doc.blocks[-1]
        if not any(k == SectionType.deliberation for k, _, _ in block_parts(last)) and VOTE_HINT.search(
            _flat(last.lines)
        ):
            deliberation = list(last.lines)
    return sections, statements, deliberation


VOTE_HINT = re.compile(r"äänesty|kannattamana", re.IGNORECASE)


# -- motions and votes in the Käsittely prose ---------------------------------------------

_NUM = r"(\d+|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + ")"
NAMEWORD = r"(?:el|af|von|de|van)\s+[A-ZÅÄÖ][\w'’-]+|[A-ZÅÄÖ][\w'’-]+"
PERSON = rf"(?:{NAMEWORD})(?:\s+(?:{NAMEWORD})){{0,3}}"
MOTION = re.compile(
    rf"(?P<prop>{PERSON})\s+(?P<verb>teki|esitti|ehdotti)\s+"
    rf"(?:(?P<sec>(?:[a-zåäö]+\s+){{0,3}}{PERSON})\s+kannattamana\s*,?\s*)?"
    r"(?P<rest>.*?)(?=(?:Puheenjohtaja|Asian käsittelyn aikana|Käsittelyn aikana|Käsittelyn kuluessa|"
    r"Valtuutettu|Kaupunginhallituksen jäsen|_{3,})|$)",
    re.DOTALL,
)
# "valtuutettu Leppikorpi valtuutettu Virtasen kannattamana ehdotti, että …" (Rauma)
MOTION_SEC_FIRST = re.compile(
    rf"(?P<prop>{PERSON})\s+(?P<sec>(?:[a-zåäö]+\s+){{0,3}}{PERSON})\s+kannattamana\s*,?\s+"
    r"(?P<verb>teki|esitti|ehdotti)\s*,?\s*"
    r"(?P<rest>.*?)(?=(?:Puheenjohtaja|Asian käsittelyn aikana|Käsittelyn aikana|Käsittelyn kuluessa|"
    r"Yleiskeskustelun aikana|Valtuutettu|_{3,})|$)",
    re.DOTALL,
)
# "Henna Palinin ehdotus valtuutettu Mikko Hietalahden kannattamana: "…"" (Pirkkala); the proposer
# is in the genitive, the text runs to the voting method or the next vote.
MOTION_NOUN = re.compile(
    rf"(?P<prop>{PERSON})\s+(?:muutos|palautus|pöydällepano)?(?:ehdotus|esitys)\s+"
    rf"(?P<sec>(?:[a-zåäö]+\s+){{0,3}}{PERSON})\s+kannattamana\s*:\s*"
    r"(?P<rest>.*?)(?=Äänestystapa|Äänestys\s+\d|Jaa\s*\(|$)",
    re.DOTALL,
)
# "… seuraavan muutosesityksen[, joka raukesi kannattamattomana]:" introduces the motion's text
INTRO = re.compile(
    r"^.*?(?:muutosesityksen|esityksen|ehdotuksen|lisäyksen)\s*"
    r"(?:,\s*joka\s+raukesi\s+kannattamattomana)?\s*:\s*"
)
UNSECONDED = re.compile(r"raukesi\s+kannattamattomana", re.IGNORECASE)
PROPOSITION = re.compile(
    r"(?:he|ne),?\s+jotka\s+kannattavat\s+(?P<jaa>.+?),?\s+äänestävät\s+jaa,?\s+ja\s+(?:he|ne),?\s+(?:jotka|ketkä)\s+"
    r"kannattavat\s+(?P<ei>.+?),?\s+äänestävät\s+ei",
    re.IGNORECASE | re.DOTALL,
)
# Hämeenlinna: "… äänestys siten, että kaupunginhallituksen pohjaehdotusta kannattavat äänestävät JAA
# ja Laitisen muutosehdotusta kannattavat äänestävät EI", boards "… ja Reiman muutosehdotusta EI".
PROPOSITION_THAT = re.compile(
    r"siten,?\s+että\s+(?P<jaa>[^.]+?)\s+kannattavat\s+äänestävät\s+jaa,?\s+ja\s+"
    r"(?P<ei>[^.]+?)(?:\s+kannattavat\s+äänestävät)?\s+ei\b",
    re.IGNORECASE | re.DOTALL,
)
RESULT = re.compile(r"Äänestyksessä\s+annettiin\b|Äänestyksen\s+tulos\s*:?", re.IGNORECASE)
# Rauma names the sides: "Suoritetussa äänestyksessä asian … jatkaminen sai 25 ääntä ja valtuutettu
# Leppikorven ym. ehdottama … sai 18 ääntä", or "… välillä, sai asian käsittelyn jatkaminen 37 ääntä
# ja Toivosen ym. ehdottama … 6 ääntä".
_CLAUSE = r"(?:\bym\.|\bmm\.|[^.])+?"  # a clause; "Leppikorven ym. ehdottama" keeps its dot
SAI_RESULT = re.compile(
    rf"äänestyksessä\s+(?:(?P<la1>{_CLAUSE})\s+sai\s+(?P<a1>{_NUM})\s+ääntä,?\s+ja\s+(?P<lb1>{_CLAUSE})\s+sai\s+"
    rf"(?P<b1>{_NUM})\s+ääntä|{_CLAUSE[:-1]}?\bsai\s+(?P<la2>{_CLAUSE})\s+(?P<a2>{_NUM})\s+ääntä,?\s+ja\s+"
    rf"(?P<lb2>{_CLAUSE})\s+(?P<b2>{_NUM})\s+ääntä)",
    re.IGNORECASE,
)
# Pirkkala: "Äänestystapa äänestyskone Jaa (Kh - pohjaehdotus) 34 ääntä Ei (Palinin ehdotus) 9 ääntä
# [Tyhjä 0 ääntä]"
JAA_EI_RESULT = re.compile(
    rf"\bJaa\s*\((?P<jaa>[^)]*)\)\s*:?\s*(?P<a>{_NUM})\s+ään\w*[,.]?\s+Ei\s*\((?P<ei>[^)]*)\)\s*:?\s*"
    rf"(?P<b>{_NUM})\s+ään\w*(?:[,.]?\s+Tyhj\w*(?:\s*\([^)]*\))?\s*:?\s*(?P<t>{_NUM}))?"
)
TYHJA_NONE = re.compile(r"^\W*Tyhjiä\s+ääniä\s+ei\s+annettu", re.IGNORECASE)
# One side of the result, either order: "61 jaa-ääntä", "55 jaa ääntä", "45 jaaääntä",
# "yksi tyhjä-ääni", "Jaa-ääniä 6", each with the voters' surnames in brackets on boards.
_SIDE = r"(?P<w>jaa|ei|tyhjä)[- ]?ään\w*|tyhjää"
COUNT = re.compile(
    rf"(?:(?P<n1>{_NUM})\s+(?:{_SIDE.replace('?P<w>', '?P<w1>')})"
    rf"|(?:{_SIDE.replace('?P<w>', '?P<w2>')})\s+(?P<n2>{_NUM}))"
    r"(?:\s*\((?P<names>[^)]*)\))?",
    re.IGNORECASE,
)
# The result runs to the chair's conclusion or the next sentence that is not a count.
RESULT_END = re.compile(r"\bjoten\b|Puheenjohtaja\s+totesi|\.\s+(?!Jaa|Ei|Tyhj)[A-ZÅÄÖ]")
CHOICE_OF = {"jaa": Choice.jaa, "ei": Choice.ei, "tyhjä": Choice.tyhja}


def _n(word: str) -> int:
    return int(word) if word.isdigit() else NUMBER_WORDS[word.lower()]


def _flat(lines: list[str]) -> str:
    return re.sub(r"\s+", " ", join_lines(lines)).strip()


TITLE_WORDS = {"valtuutettu", "varavaltuutettu", "jäsen", "puheenjohtaja", "varapuheenjohtaja"}


def _person(raw: str) -> str:
    """The name at the end of "ELINVOIMA Valtuutettu Loviisa Kaartokallio" or "kaupunginhallituksen
    I varapuheenjohtaja Mika Kasonen": everything after the last title word, heading word in
    capitals or lowercase word."""
    words = normalize_name(raw).split()
    cut = 0
    for i, w in enumerate(words):
        if w.lower() in TITLE_WORDS or w.islower() or (w.isupper() and len(w) > 1) or w in ("I", "II"):
            cut = i + 1
    # keep a lowercase particle that starts a surname ("el Issaoui")
    if cut and words[cut - 1] in ("el", "af", "von", "de", "van"):
        cut -= 1
    return " ".join(words[cut:])


def _kind(text: str) -> MotionKind:
    low = text.lower()
    if "palaut" in low:
        return MotionKind.send_back
    if "pöydälle" in low:
        return MotionKind.table
    if "pon" in low and ("ponne" in low or "ponsi" in low) or "toivomu" in low:
        return MotionKind.resolution
    return MotionKind.counter_proposal


def _nominative(name: str) -> str:
    """ "Henna Palinin" → "Henna Palin", "Veli-Matti Ahtiaisen" → "Veli-Matti Ahtiainen": a guess at
    the surname's nominative for a proposer printed in the genitive (resolution matches fuzzily)."""
    words = name.split()
    if not words:
        return name
    w = words[-1]
    if w.endswith("sen"):
        w = w[:-3] + "nen"
    elif re.search(r"[^aeiouyäö]in$", w):
        w = w[:-2]
    elif w.endswith("n"):
        w = w[:-1]
    return " ".join([*words[:-1], w])


def _motions_at(text: str) -> list[tuple[int, Motion]]:
    out = []
    taken: list[tuple[int, int]] = []
    for m in [*MOTION_SEC_FIRST.finditer(text), *MOTION_NOUN.finditer(text), *MOTION.finditer(text)]:
        if any(a <= m.start() < b for a, b in taken):
            continue
        prop = _person(m.group("prop"))
        if m.re is MOTION_NOUN:
            prop = _nominative(prop)
        if not prop or prop.lower().startswith(("puheenjohtaja", "kaupunginjohtaja")):
            continue
        rest = m.group("rest").strip()
        unseconded = bool(UNSECONDED.search(rest[:120]))
        if not m.group("sec") and not unseconded:
            continue  # "esitti … lisäystä, joka hyväksyttiin yksimielisesti" is not a motion
        body = INTRO.sub("", rest, count=1)
        body = re.sub(r"^,?\s*että\s+", "", body)
        motion = Motion(
            kind=_kind(rest[:160]),
            proposer_ref=PersonRef(raw=prop),
            seconder_refs=[PersonRef(raw=_person(m.group("sec")))] if m.group("sec") else [],
            text=strip_pii(body.strip() or rest),
            outcome=Outcome.rejected if unseconded else None,
        )
        out.append((m.start(), motion))
        taken.append((m.start(), m.end()))
    return sorted(out, key=lambda x: x[0])


def parse_motions(lines: list[str]) -> list[Motion]:
    return parse_case(lines)[0]


@dataclass
class TwebProse(ProseVote):
    jaa_label: str = ""
    ei_label: str = ""
    names: dict[Choice, list[str]] = field(default_factory=dict)
    prop_end: int = -1  # where its voting proposal ends in the text, -1 when none
    start: int = 0  # where its result sentence starts


def _names(text: str | None) -> list[str]:
    if not text:
        return []
    return [n.strip() for n in re.split(r",|\.\s+|\s+ja\s+", text) if n.strip()]


def _short_label(text: str) -> str:
    """ "valtuutettu Eerolan esittämää ja valtuutettu Bibani kannattamaa muutosesitystä" →
    "Eerolan muutosesitys"; "kaupunginhallituksen pohjaesitystä" → "pohjaesitys"."""
    t = re.sub(r"\s+", " ", text).strip()
    m = re.search(rf"({NAMEWORD})\s+esittämää.*?(\w*(?:esitys|ehdotus)\w*)$", t)
    if m:
        return f"{m.group(1)} {re.sub(r'(tä|ta)$', '', m.group(2))}"
    t = re.sub(r"(esitystä|ehdotusta)$", lambda x: x.group(1)[:-2], t)
    t = re.sub(r"(esitystään)$", "esitys", t)
    return t


def _result_end(text: str, start: int) -> re.Match | None:
    """The first RESULT_END outside the voters' brackets ("Kivimäki, Nummela. Rämö" is a typo)."""
    for e in RESULT_END.finditer(text, start):
        seg = text[start : e.start()]
        if seg.count("(") <= seg.count(")"):
            return e
    return None


def parse_prose(lines: list[str]) -> list[TwebProse]:
    text = _flat(lines)
    out = []
    props = sorted([*PROPOSITION.finditer(text), *PROPOSITION_THAT.finditer(text)], key=lambda p: p.start())
    for m in RESULT.finditer(text):
        end = _result_end(text, m.end())
        window = text[m.end() : end.start() if end else len(text)]
        counts: dict[Choice, int] = {}
        names: dict[Choice, list[str]] = {}
        for c in COUNT.finditer(window):
            word = (c.group("w1") or c.group("w2") or "tyhjä").lower()
            choice = CHOICE_OF[word]
            if choice in counts:
                continue
            counts[choice] = _n(c.group("n1") or c.group("n2"))
            if c.group("names"):
                names[choice] = _names(c.group("names"))
        if Choice.jaa not in counts or Choice.ei not in counts:
            continue
        prop = next((p for p in reversed(props) if p.end() <= m.start()), None)
        # a proposition belongs to the first result after it
        if prop is not None and any(o.prop_end == prop.end() for o in out):
            prop = None
        e = text.find(". ", (end.end() if end else m.end()))
        sentence = text[m.start() : len(text) if e < 0 else e + 1].strip()
        out.append(
            TwebProse(
                a=counts[Choice.jaa],
                b=counts[Choice.ei],
                tyhja=counts.get(Choice.tyhja, 0),
                sentence=sentence,
                jaa_label=_short_label(prop.group("jaa")) if prop else "",
                ei_label=_short_label(prop.group("ei")) if prop else "",
                names=names,
                prop_end=prop.end() if prop else -1,
                start=m.start(),
            )
        )
    for m in SAI_RESULT.finditer(text):
        i = "1" if m.group("a1") else "2"
        tail = text[m.end() : m.end() + 40]
        out.append(
            TwebProse(
                a=_n(m.group("a" + i)),
                b=_n(m.group("b" + i)),
                tyhja=0,
                sentence=text[m.start() : m.end()]
                + (" " + tail.split(".")[0] + "." if TYHJA_NONE.match(tail) else ""),
                jaa_label=_side_label(m.group("la" + i)),
                ei_label=_side_label(m.group("lb" + i)),
                start=m.start(),
            )
        )
    for m in JAA_EI_RESULT.finditer(text):
        out.append(
            TwebProse(
                a=_n(m.group("a")),
                b=_n(m.group("b")),
                tyhja=_n(m.group("t")) if m.group("t") else 0,
                sentence=m.group(0),
                jaa_label=m.group("jaa").strip(),
                ei_label=m.group("ei").strip(),
                start=m.start(),
            )
        )
    return sorted(out, key=lambda o: o.start)


def _side_label(text: str) -> str:
    """ "valtuutettu Leppikorven ym. ehdottama asian palauttaminen uudelleen valmisteluun" →
    "Leppikorven ym. ehdottama asian palauttaminen uudelleen valmisteluun"."""
    t = re.sub(r"\s+", " ", text).strip(" ,")
    t = re.sub(r"^(?:asian\s+käsittelyn\s+jatkamisen\s+ja\s+.*?välillä,?\s*)", "", t)
    return re.sub(r"^(?:valtuutettu|varavaltuutettu|jäsen)\s+", "", t)


def parse_case(lines: list[str]) -> tuple[list[Motion], list[TwebProse]]:
    """Motions and votes of one Käsittely. A vote decides the latest motion before it whose
    proposer the Ei side names in the genitive ("valtuutettu Eerolan … muutosesitystä")."""
    text = _flat(lines)
    if SWEDISH_CASE.search(text):
        return parse_case_sv(text)
    placed = _motions_at(text)
    prose = parse_prose(lines)
    for pv in prose:
        ei_words = [w.strip(".,()") for w in pv.ei_label.split()[:3]]
        jaa_words = [w.strip(".,()") for w in pv.jaa_label.split()[:3]]
        before = [mo for pos, mo in placed if pos < pv.start]
        for mo in reversed(before):
            surname = mo.proposer_ref.raw.split()[-1]
            if any(w and (_is_genitive(w, surname) or w == surname) for w in ei_words):
                mo.outcome = Outcome.adopted if pv.b > pv.a else Outcome.rejected
                break
            if any(w and (_is_genitive(w, surname) or w == surname) for w in jaa_words):
                mo.outcome = Outcome.adopted if pv.a > pv.b else Outcome.rejected
                break
        else:
            # no name to go by ("Leppikorven" for Leppikorpi, "Ei (palautetaan)"): the motion just
            # before the vote, when the Ei side is that kind of motion or the vote is a Jaa/Ei block
            prev = max((o.start for o in prose if o.start < pv.start), default=-1)
            open_ = [mo for pos, mo in placed if prev < pos < pv.start and mo.outcome is None]
            kind = _kind(pv.ei_label) if re.search(r"palaut|pöydälle", pv.ei_label, re.I) else None
            if open_ and (kind == open_[-1].kind or JAA_EI_RESULT.match(pv.sentence)):
                open_[-1].outcome = Outcome.adopted if pv.b > pv.a else Outcome.rejected
    return [mo for _, mo in placed], prose


# -- vote report PDF ----------------------------------------------------------------------

VOTE_NAME = re.compile(r"^Vote name:\s*JAA\s*=\s*(?P<jaa>.*?)\s+EI\s*=\s*(?P<ei>.*)$", re.IGNORECASE)
AGENDA = re.compile(r"^Agenda name:\s*§\s*(\d+)")
VOTE_START = re.compile(r"^Vote start:\s*(\d{1,2})[./](\d{1,2})[./](\d{4})")
VOTES_TOTAL = re.compile(r"^Votes:\s*(\d+)")
TOTAL_ROW = re.compile(r"^(JAA|EI|Tyhjää|Tyhjä|Poissa)\s+(\d+)(?:\s+[\d,.]+\s*%)?$", re.IGNORECASE)
CHOICE_HEAD = re.compile(r"^(JAA|EI|Tyhjää|Tyhjä|Poissa|Ei äänestänyt)$", re.IGNORECASE)
CHOICES = {
    "jaa": Choice.jaa,
    "ei": Choice.ei,
    "tyhjää": Choice.tyhja,
    "tyhjä": Choice.tyhja,
    "poissa": Choice.poissa,
}
PARTY = re.compile(r"^(?P<name>.+?)\s+(?P<party>[a-zåäö][a-zåäö.]{0,7})$")


@dataclass
class ReportVote(PdfVote):
    date: dt.date | None = None
    groups: dict[str, str] = field(default_factory=dict)


def parse_vote_report(lines: list[str]) -> list[ReportVote]:
    votes: list[ReportVote] = []
    cur: ReportVote | None = None
    state = "head"
    choice: Choice | None = None
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line.startswith("--- page "):
            continue
        if m := VOTE_NAME.match(line):
            cur = ReportVote(jaa_label=m.group("jaa").strip(), ei_label=m.group("ei").strip())
            votes.append(cur)
            state, choice = "head", None
            continue
        if cur is None:
            continue
        if state == "head":
            if m := AGENDA.match(line):
                cur.pykala = int(m.group(1))
            elif m := VOTE_START.match(line):
                cur.date = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            elif m := VOTES_TOTAL.match(line):
                cur.total = int(m.group(1))
            elif (m := TOTAL_ROW.match(line)) and line != "":
                c = CHOICES[m.group(1).lower()]
                cur.counts.setdefault(c, int(m.group(2)))
            elif line.startswith("Group Voting Results"):
                state = "groups"
            elif line.startswith("Individual Voting Results"):
                state = "voters"
            continue
        if state == "groups":
            if line.startswith("Individual Voting Results"):
                state = "voters"
            continue
        if m := CHOICE_HEAD.match(line):
            choice = CHOICES.get(m.group(1).lower())
            continue
        if choice is None:
            cur.leftover.append(line)
            continue
        name, party = line, None
        if pm := PARTY.match(line):
            name, party = pm.group("name"), pm.group("party")
        cur.ballots.append((name, choice))
        if party:
            cur.groups[name] = party
    return votes


# -- Swedish Beslutets behandling (Raasepori) ----------------------------------------------
# "Werner Orre föreslog att ärendet remitteras …", "Sven Holmberg och Roger Hafström understödde
# Orres förslag", the proposition "Stadsstyrelsens förslag = Ja / Orres förslag = Nej" and the
# result "I omröstningen avgavs 34 ja-röster, sex (6) nej samt tre (3) nedlagda röster".

SWEDISH_CASE = re.compile(r"\b(?:föreslog|omröstningen)\b")
SV_NUMBERS = {
    "noll": 0, "en": 1, "ett": 1, "två": 2, "tre": 3, "fyra": 4, "fem": 5, "sex": 6, "sju": 7, "åtta": 8,
    "nio": 9, "tio": 10, "elva": 11, "tolv": 12, "tretton": 13, "fjorton": 14, "femton": 15,
    "sexton": 16, "sjutton": 17, "arton": 18, "nitton": 19, "tjugo": 20,
}  # fmt: skip
MOTION_SV = re.compile(rf"(?P<prop>{PERSON})\s+föreslog\s+(?:att\s+)?(?P<rest>[^.]*?)\.(?=\s|$)")
SECONDED_SV = re.compile(
    rf"(?P<secs>{PERSON}(?:\s*(?:,|och)\s*{PERSON})*)\s+understödde\s+(?P<gen>{NAMEWORD})\s+(?:förslag|motförslag)"
)
UNSECONDED_SV = re.compile(r"förföll\s+(?:i\s+brist\s+på|utan)\s+understöd", re.IGNORECASE)
PROPOSITION_SV = re.compile(
    r"(?P<jaa>[A-ZÅÄÖ][^.:=]*?)\s*=\s*Ja\b[\s,;]*(?P<ei>[A-ZÅÄÖ][^.:=]*?)\s*=\s*Nej\b"
)
RESULT_SV = re.compile(r"(?:I|Vid)\s+omröstningen\s+avgavs\b", re.IGNORECASE)
COUNT_SV = re.compile(
    r"(?:(?:[a-zåäö]+\s+)?\((?P<p>\d+)\)|(?P<d>\d+)|(?P<w>[a-zåäö]+))\s+"
    r"(?P<side>ja|nej|nedlagd\w*|blank\w*)\b",
    re.IGNORECASE,
)
SV_SIDE = {"ja": Choice.jaa, "nej": Choice.ei}


def _sv_kind(text: str) -> MotionKind:
    low = text.lower()
    if "remitt" in low or "återremitt" in low:
        return MotionKind.send_back
    if "bordl" in low:
        return MotionKind.table
    return MotionKind.counter_proposal


def _sv_genitive(gen: str, surname: str) -> bool:
    g, s = gen.lower(), surname.lower()
    return g in (s + "s", s, s + "'s") or (s.endswith(("s", "x", "z")) and g == s)


def parse_case_sv(text: str) -> tuple[list[Motion], list[TwebProse]]:
    placed: list[tuple[int, Motion]] = []
    for m in MOTION_SV.finditer(text):
        prop = _person(m.group("prop"))
        if not prop or prop.split()[0].lower() in ("ordförande", "stadsdirektören"):
            continue
        surname = prop.split()[-1]
        after = text[m.end() :]
        sec = next((x for x in SECONDED_SV.finditer(after) if _sv_genitive(x.group("gen"), surname)), None)
        unseconded = bool(UNSECONDED_SV.search(after[:200]))
        if not sec and not unseconded:
            continue
        seconders = [_person(n) for n in re.split(r",|\s+och\s+", sec.group("secs"))] if sec else []
        rest = m.group("rest").strip()
        placed.append(
            (
                m.start(),
                Motion(
                    kind=_sv_kind(rest),
                    proposer_ref=PersonRef(raw=prop),
                    seconder_refs=[PersonRef(raw=n) for n in seconders if n],
                    text=strip_pii(rest),
                    outcome=Outcome.rejected if unseconded else None,
                ),
            )
        )
    props = list(PROPOSITION_SV.finditer(text))
    prose: list[TwebProse] = []
    for r in RESULT_SV.finditer(text):
        e = re.search(r"\.(?=\s|$)", text[r.end() :])
        end = r.end() + (e.start() if e else len(text) - r.end())
        counts: dict[Choice, int] = {}
        for c in COUNT_SV.finditer(text[r.end() : end]):
            raw = c.group("p") or c.group("d") or (c.group("w") or "").lower()
            n = int(raw) if raw.isdigit() else SV_NUMBERS.get(raw)
            if n is None:
                continue
            choice = SV_SIDE.get(c.group("side").lower(), Choice.tyhja)
            counts.setdefault(choice, n)
        if Choice.jaa not in counts or Choice.ei not in counts:
            continue
        prop = next((p for p in reversed(props) if p.end() <= r.start()), None)
        jaa = re.sub(r"\s+", " ", prop.group("jaa")).strip() if prop else ""
        ei = re.sub(r"\s+", " ", prop.group("ei")).strip() if prop else ""
        prose.append(
            TwebProse(
                a=counts[Choice.jaa],
                b=counts[Choice.ei],
                tyhja=counts.get(Choice.tyhja, 0),
                sentence=text[r.start() : end + 1].strip(),
                jaa_label=jaa,
                ei_label=ei,
                prop_end=prop.end() if prop else -1,
                start=r.start(),
            )
        )
        before = [mo for pos, mo in placed if pos < r.start() and mo.outcome is None]
        # "Remittering = Ja": the send-back is the Ja side; otherwise the motion is the Nej side
        if re.match(r"(?:åter)?remitt|bordl", jaa, re.IGNORECASE):
            mo = next(
                (x for x in reversed(before) if x.kind in (MotionKind.send_back, MotionKind.table)), None
            )
            if mo:
                mo.outcome = Outcome.adopted if counts[Choice.jaa] > counts[Choice.ei] else Outcome.rejected
        elif ei:
            gen = ei.split()[0]
            mo = next(
                (x for x in reversed(before) if _sv_genitive(gen, x.proposer_ref.raw.split()[-1])), None
            )
            if mo:
                mo.outcome = Outcome.adopted if counts[Choice.ei] > counts[Choice.jaa] else Outcome.rejected
    return [mo for _, mo in placed], prose
