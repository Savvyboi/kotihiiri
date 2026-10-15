"""Page parsers for Dynasty at espoo.oncloudos.com (PLAN.md §7.2). Pure functions: HTML in, plain
data out.

Structure inspected by hand on 2026-10-13 (PLAN.md §16, S10). The parsers key on visible text,
table headers and URL shapes, not on CSS classes:

- `meeting_frames`: a table Toimielin | Viimeisin kokous | Kokouspäivämäärä, one row per body,
  the name linking to `?page=meetings&id={bodyId}`;
- `meetings`: per year ("Vuosi 2026") a table Kokouspäivämäärä | Asiakirjatyyppi whose label
  ("Esityslista" / "Pöytäkirja") links to `?page=meeting&id={meetingId}`;
- `meeting`: an h1 "{Body}  Pöytäkirja dd.mm.yyyy klo 17.30 - 19.53 ⁄ Tarkastettu  {place}", the
  minutes PDF link `/kokous/{meetingId}.PDF`, a table Pykälä | Liitteet | Otsikko linking to
  `?page=meetingitem&id={meetingId}-{n}`, and a table Osallistuja | Tehtävä;
- `meetingitem`: one text block with heading lines (Päätösehdotus, Käsittely, Päätös, Selostus,
  Päätöshistoria, Liitteet, Oheismateriaali, Tiedoksi), which may be plain paragraphs rather than
  heading tags, so headings are recognised by their text.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..htmlblocks import Link, all_links, blocks, clean
from ..models import Attachment, AttachmentKind, Section, SectionType, Stage
from ..text import collapse_ws, strip_pii

BASE = "https://espoo.oncloudos.com"
CGI = BASE + "/cgi/DREQUEST.PHP"
# Relative links resolve against the host being parsed; adapters set it with `base_url(...)`.
_CGI: ContextVar[str] = ContextVar("dynasty_cgi", default=CGI)


@contextmanager
def base_url(base: str) -> Iterator[None]:
    """Resolve links against `{base}/cgi/DREQUEST.PHP` (one install per municipality, §18.1)."""
    token = _CGI.set(base.rstrip("/") + "/cgi/DREQUEST.PHP")
    try:
        yield
    finally:
        _CGI.reset(token)


DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
BODY_HREF = re.compile(r"[?&]page=meetings&id=(\d+)\b")
MEETING_HREF = re.compile(r"[?&]page=meeting&id=(\d+)\b")
ITEM_HREF = re.compile(r"[?&]page=meetingitem&id=(\d+)-(\d+)\b")
PDF_HREF = re.compile(r"/kokous/(\d+)(?:-(\d+))?(?:-(\d+))?\.PDF$", re.IGNORECASE)
TIME_RANGE = re.compile(r"klo\s+(\d{1,2})[.:](\d{2})(?:\s*-\s*(?:(\d{1,2})[.:](\d{2}))?)?", re.IGNORECASE)
STAGE_WORDS = {"esityslista": Stage.agenda, "pöytäkirja": Stage.minutes}


def decode(content: bytes, declared: str | None = None) -> str:
    """Dynasty serves listing pages as ISO-8859-1 and item pages as UTF-8, and the declared charset
    is not always right. Valid UTF-8 with non-ASCII bytes is UTF-8; otherwise use the declared
    charset (header or meta tag), falling back to Windows-1252 (a superset of ISO-8859-1)."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if declared is None:
        m = re.search(rb"charset=[\"']?([\w-]+)", content[:4096], re.IGNORECASE)
        declared = m.group(1).decode("ascii") if m else None
    for enc in (declared, "cp1252", "iso-8859-1"):
        if not enc:
            continue
        try:
            return content.decode("cp1252" if enc.lower() in ("iso-8859-1", "latin-1", "latin1") else enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("iso-8859-1")


def parse_date(text: str) -> dt.date | None:
    m = DATE.search(text)
    return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


@dataclass
class Row:
    cells: list[str]
    links: list[Link]


def table_rows(html: str, base: str | None = None) -> list[list[Row]]:
    """Every table on the page as rows of cell texts plus the row's links (header rows included)."""
    tree = HTMLParser(html)
    tables: list[list[Row]] = []
    for table in tree.css("table"):
        rows: list[Row] = []
        for tr in table.css("tr"):
            if tr.parent is not None and tr.parent.tag not in ("table", "tbody", "thead", "tfoot"):
                continue
            # skip rows of nested tables; they are listed with their own table
            owner = tr.parent if tr.parent.tag == "table" else tr.parent.parent
            if owner is None or owner.mem_id != table.mem_id:
                continue
            cells = [clean(c.text(deep=True, separator=" ")) for c in tr.css("th, td")]
            links = []
            for a in tr.css("a[href]"):
                href = (a.attributes.get("href") or "").strip()
                if href and not href.startswith(("#", "mailto:", "javascript:")):
                    links.append(
                        Link(clean(a.text(deep=True, separator=" ")), urljoin(base or _CGI.get(), href))
                    )
            if any(cells):
                rows.append(Row(cells, links))
        tables.append(rows)
    return tables


# -- bodies -------------------------------------------------------------------------------


def parse_bodies(html: str) -> dict[str, str]:
    """Dynasty body id → name, from `?page=meeting_frames`. Rows without a link (bodies with no
    published meetings, such as "Testitoimielin") are skipped."""
    out: dict[str, str] = {}
    for link in all_links(html, _CGI.get()):
        m = BODY_HREF.search(link.href)
        if m and link.text and not STAGE_WORDS.get(link.text.lower()):
            out.setdefault(m.group(1), link.text)
    return out


# -- meeting listing ----------------------------------------------------------------------


@dataclass
class ListingRow:
    meeting_id: str
    date: dt.date
    stage: Stage
    url: str


def parse_meetings(html: str) -> list[ListingRow]:
    """Every meeting of a body (all years on one page), as listed. The label is the stage."""
    rows: dict[str, ListingRow] = {}
    for table in table_rows(html):
        for row in table:
            date = next((d for c in row.cells if (d := parse_date(c))), None)
            for link in row.links:
                m = MEETING_HREF.search(link.href)
                stage = STAGE_WORDS.get(link.text.lower())
                if m and stage and date:
                    rows.setdefault(m.group(1), ListingRow(m.group(1), date, stage, link.href))
    return list(rows.values())


# -- meeting page -------------------------------------------------------------------------


@dataclass
class AgendaRow:
    ordinal: int
    pykala: int | None
    title: str
    url: str


@dataclass
class Participant:
    name: str
    role: str


@dataclass
class MeetingPage:
    stage: Stage | None
    date: dt.date | None
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = None
    minutes_pdf: str | None = None
    published: dt.date | None = None
    rows: list[AgendaRow] = field(default_factory=list)
    participants: list[Participant] = field(default_factory=list)


def _hhmm(h: str | None, m: str | None) -> str | None:
    return f"{int(h):02d}:{m}" if h and m else None


def parse_meeting(html: str, meeting_id: str) -> MeetingPage:
    bl = blocks(html, _CGI.get())
    h1 = next((b.text for b in bl if b.kind == "h1"), "")
    stage = next((s for w, s in STAGE_WORDS.items() if re.search(rf"\b{w}\b", h1, re.IGNORECASE)), None)
    page = MeetingPage(stage=stage, date=parse_date(h1))
    if m := TIME_RANGE.search(h1):
        page.start_time = _hhmm(m.group(1), m.group(2))
        page.end_time = _hhmm(m.group(3), m.group(4))
        rest = h1[m.end() :]
        rest = re.sub(r"^[\s⁄/|-]*(?:tarkastettu|tarkastamaton)?[\s⁄/|-]*", "", rest, flags=re.IGNORECASE)
        page.location = rest.strip() or None
    for b in bl:
        low = b.text.lower()
        if low.startswith("paikka:") and not page.location:
            page.location = b.text.split(":", 1)[1].strip() or None
        elif low.startswith("julkaistu"):
            page.published = parse_date(b.text)

    for link in all_links(html, _CGI.get()):
        m = PDF_HREF.search(link.href)
        if m and m.group(1) == meeting_id and not m.group(2):
            page.minutes_pdf = page.minutes_pdf or link.href

    seen: set[int] = set()
    for table in table_rows(html):
        header = [c.lower() for c in table[0].cells] if table else []
        if "osallistuja" in header:
            ni, ri = header.index("osallistuja"), header.index("tehtävä") if "tehtävä" in header else None
            for row in table[1:]:
                if len(row.cells) > ni and row.cells[ni]:
                    role = row.cells[ri] if ri is not None and ri < len(row.cells) else ""
                    page.participants.append(Participant(row.cells[ni], role))
            continue
        for row in table:
            for link in row.links:
                m = ITEM_HREF.search(link.href)
                if not m or m.group(1) != meeting_id or not link.text:
                    continue
                ordinal = int(m.group(2))
                if ordinal in seen:
                    continue
                seen.add(ordinal)
                pykala = next((int(c) for c in row.cells if c.isdigit()), None)
                page.rows.append(AgendaRow(ordinal, pykala, link.text, link.href))
    page.rows.sort(key=lambda r: r.ordinal)
    return page


# -- item page ----------------------------------------------------------------------------

D, P, DL, BG = SectionType.decision, SectionType.proposal, SectionType.deliberation, SectionType.background
# Lines that open a part of the item text (lowercase, without a trailing colon).
SECTION_HEADINGS: dict[str, SectionType | str | None] = {
    "päätösehdotus": P, "päätösehdotus esittelijä": P, "ehdotus": P, "esitys": P,
    "käsittely": DL,
    "päätös": D,
    "selostus": BG, "perustelut": BG, "selostus ja perustelut": BG,
    "pöytäkirjamerkintä": SectionType.statement, "pöytäkirjamerkinnät": SectionType.statement,
    "pöytäkirjalausuma": SectionType.statement, "pöytäkirjalausumat": SectionType.statement,
    "eriävä mielipide": SectionType.dissent, "eriävät mielipiteet": SectionType.dissent,
    "tiedoksi": SectionType.other,
    "päätöshistoria": "history", "aikaisempi käsittely": "history",
    "liitteet": "attachments", "oheismateriaali": "attachments_supp",
    "muutoksenhaku": None, "muutoksenhakuohje": None, "valitusosoitus": None,
    "oikaisuvaatimusohje": None, "lisätiedot": None,
}  # fmt: skip
HISTORY_END = {"liitteet", "oheismateriaali", "tiedoksi", "muutoksenhaku", "muutoksenhakuohje"}
PRESENTER_INLINE = re.compile(r"^päätösehdotus\s+esittelijä\s*:?\s*(.+)$", re.IGNORECASE)
HISTORY_HEAD = re.compile(r"^(.+?)\s+(\d{1,2}\.\d{1,2}\.\d{4})\s*§\s*(\d+)\s*$")
CASE_NUMBER = re.compile(r"^Asianumero\s+(\S+)", re.IGNORECASE)
PYKALA_LINE = re.compile(r"^§\s*(\d+)$")
PREPARERS = re.compile(r"^Valmistelijat?\s*(?:/\s*lisätiedot)?\s*:?$", re.IGNORECASE)
CHROME = re.compile(
    r"^(Edellinen asia|Seuraava asia|Navigointi|Kokousasian teksti|Muutoksenhakuohje|Kokousasia)\b"
    r"|^\(pdf [\d.,]+ [km]b\)$|\bEdellinen asia\b.*\bSeuraava asia\b",
    re.IGNORECASE,
)
CONTACT_LINE = re.compile(r"^(Puhelinnumero|Puhelin|puh\.?|Sähköposti)\b|@", re.IGNORECASE)


@dataclass
class ItemPage:
    title: str | None = None
    pykala: int | None = None
    case_number: str | None = None
    presenter: str | None = None
    preparers: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    deliberation_lines: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    item_pdf: str | None = None

    def has_decision(self) -> bool:
        return any(s.type == SectionType.decision for s in self.sections)


def _heading_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().rstrip(":").strip()).lower()


def _section_text(lines: list[str]) -> str:
    return collapse_ws(strip_pii("\n\n".join(lines)))


def _attachment_title(text: str) -> str:
    text = re.sub(r"\s*\(pdf [\d.,\s]+[kmg]?b\)\s*$", "", text, flags=re.IGNORECASE)
    return re.sub(r"^(Liite\s+\d+)(?=\S)", r"\1 ", text).strip()  # "Liite 1Äänestyslistat" → "Liite 1 Ä…"


HEADING_WORDS = (
    "Päätösehdotus", "Käsittely", "Päätös", "Selostus", "Perustelut", "Päätöshistoria", "Liitteet",
    "Oheismateriaali", "Tiedoksi", "Pöytäkirjamerkintä", "Eriävä mielipide",
)  # fmt: skip
# The item text comes from a word processor: a heading and its first paragraph can share one <p>,
# "<span>Päätös</span><span>&#xa0;</span><span>Puheenjohtaja totesi …</span>". Break after the heading,
# except in the two-word heading "Päätösehdotus Esittelijä".
INLINE_HEADING = re.compile(
    r"(<span[^>]*>\s*(?:" + "|".join(HEADING_WORDS) + r")\s*</span>)"
    r"(\s*<span[^>]*>(?:\s|&#xa0;|&nbsp;|\xa0)*</span>)(?=\s*<span)(?!\s*<span[^>]*>\s*Esittelijä)",
    re.IGNORECASE,
)


def _parts(html: str) -> tuple[str, list[tuple[str, list[Link]]]]:
    """The item text (`div.data-part.meetingitem`) and the link lists of the other data parts
    (attachments, supplementary material) with their caption. Pages without these parts are parsed
    whole."""
    tree = HTMLParser(html)
    text = tree.css_first("div.data-part.meetingitem")
    others: list[tuple[str, list[Link]]] = []
    for part in tree.css("div.data-part"):
        classes = part.attributes.get("class") or ""
        if "meetingitem" in classes or "page-navigation" in classes:
            continue
        cap = part.css_first("caption") or part.css_first(".data-part-caption")
        caption = clean(cap.text(deep=True, separator=" ")) if cap else ""
        links = [
            Link(clean(a.text(deep=True, separator=" ")), urljoin(_CGI.get(), a.attributes.get("href") or ""))
            for a in part.css("a[href]")
        ]
        others.append((f"{classes} {caption}".lower(), links))
    return (text.html if text is not None else html) or html, others


def parse_item(html: str) -> ItemPage:
    page = ItemPage()
    for link in all_links(html, _CGI.get()):
        m = PDF_HREF.search(link.href)
        if m and m.group(2) and not m.group(3):
            page.item_pdf = page.item_pdf or link.href
    text_html, parts = _parts(html)
    links = all_links(text_html, _CGI.get())
    bl = blocks(INLINE_HEADING.sub(r"\1<br>", text_html), _CGI.get())

    # Start after the "Kokousasian teksti" heading when there is one (the site chrome is above it).
    start = next((i + 1 for i, b in enumerate(bl) if b.text.lower() == "kokousasian teksti"), 0)
    if not start:
        start = next((i + 1 for i, b in enumerate(bl) if b.kind == "h1"), 0)

    mode = "header"
    kind: SectionType | None = None
    heading: str | None = None
    lines: list[str] = []
    history: list[Section] = []
    hist_heading: str | None = None
    hist_lines: list[str] = []
    expect_presenter = False
    expect_title = False
    attachment_rows: list[tuple[str, str]] = []  # (mode, row text)

    def close_section() -> None:
        nonlocal lines
        if mode == "section" and kind is not None and lines:
            text = _section_text(lines)
            if text:
                page.sections.append(Section(type=kind, heading=heading, text=text))
        lines = []

    def close_history() -> None:
        nonlocal hist_lines
        if hist_heading and hist_lines:
            text = _section_text(hist_lines)
            if text:
                history.append(Section(type=SectionType.history, heading=hist_heading, text=text))
        hist_lines = []

    for b in bl[start:]:
        if b.kind == "table":
            rows = [" | ".join(c for c in r if c) for r in b.rows]
            if any(CHROME.search(r) for r in rows):
                continue
        text = b.text
        if b.kind != "table" and CHROME.search(text):
            continue
        key = _heading_key(text) if b.kind != "table" else ""

        if mode == "header":
            if b.kind == "table":
                if b.rows and PREPARERS.match(b.rows[0][0] if b.rows[0] else ""):
                    page.preparers = [
                        r[0] for r in b.rows[1:] if r and r[0] and not CONTACT_LINE.search(r[0])
                    ]
                continue
            if m := CASE_NUMBER.match(text):
                page.case_number = m.group(1)
                continue
            if m := PYKALA_LINE.match(text):
                page.pykala = int(m.group(1))
                expect_title = True
                continue
            if expect_title and key not in SECTION_HEADINGS and not PRESENTER_INLINE.match(text):
                page.title = text
                expect_title = False
                continue
        if mode == "history":
            if HISTORY_HEAD.match(text) and b.kind != "table":
                close_history()
                hist_heading = text
                continue
            if key in HISTORY_END:
                close_history()
                mode = "chrome"
            else:
                if b.kind == "table":
                    hist_lines.extend(" | ".join(r) for r in b.rows)
                elif not CONTACT_LINE.search(text):
                    hist_lines.append(text)
                continue

        if b.kind != "table" and (key in SECTION_HEADINGS or PRESENTER_INLINE.match(text)):
            close_section()
            heading = text
            role = SECTION_HEADINGS.get(key, P)
            expect_presenter = key == "päätösehdotus esittelijä"
            if expect_presenter:
                heading = "Päätösehdotus"
            if m := PRESENTER_INLINE.match(text):
                page.presenter = strip_pii(m.group(1).strip())
                heading = "Päätösehdotus"
            if role == "history":
                mode, hist_heading, hist_lines = "history", None, []
            elif role is None or isinstance(role, SectionType):
                kind = role
                mode = "section" if kind is not None else "drop"
            else:
                mode = role  # attachments, attachments_supp
            continue

        if mode == "section":
            if expect_presenter and b.kind != "table":
                expect_presenter = False
                if not page.presenter and len(text) < 120 and not text.endswith((".", ":")):
                    page.presenter = strip_pii(text)
                    continue
            expect_presenter = False
            if b.kind == "table":
                lines.extend(" | ".join(r) for r in b.rows)
            elif not CONTACT_LINE.search(text):
                lines.append(text)
                if kind == SectionType.deliberation:
                    page.deliberation_lines.append(text)
        elif mode in ("attachments", "attachments_supp"):
            if b.kind == "table":
                attachment_rows.extend((mode, " ".join(r)) for r in b.rows)
            else:
                attachment_rows.append((mode, text))
    close_section()
    if mode == "history":
        close_history()
    page.sections.extend(history)
    page.attachments = _part_attachments(parts) or _attachments(attachment_rows, links)
    return page


def _part_attachments(parts: list[tuple[str, list[Link]]]) -> list[Attachment]:
    out: list[Attachment] = []
    seen: set[str] = set()
    for label, links in parts:
        if "attachment" in label or "liitteet" in label:
            kind = AttachmentKind.attachment
        elif "suplement" in label or "supplement" in label or "oheismateriaali" in label:
            kind = AttachmentKind.supplementary
        else:
            continue
        for lk in links:
            m = PDF_HREF.search(lk.href)
            if m and m.group(3) and m.group(3) != "0" and lk.text and lk.href not in seen:
                seen.add(lk.href)
                out.append(Attachment(title=_attachment_title(lk.text), url=lk.href, kind=kind))
    return out


def _attachments(rows: list[tuple[str, str]], links: list[Link]) -> list[Attachment]:
    """Attachment rows hold the title as a link to /kokous/{meetingId}-{n}-{attachmentId}.PDF. Some
    pages repeat the list without links; those rows are skipped."""
    pdfs = [
        lk for lk in links if (m := PDF_HREF.search(lk.href)) and m.group(3) and m.group(3) != "0" and lk.text
    ]
    out: list[Attachment] = []
    seen: set[str] = set()
    for mode, row in rows:
        for lk in pdfs:
            if lk.href in seen or lk.text not in row:
                continue
            seen.add(lk.href)
            kind = AttachmentKind.supplementary if mode == "attachments_supp" else AttachmentKind.attachment
            out.append(Attachment(title=_attachment_title(lk.text), url=lk.href, kind=kind))
    return out
