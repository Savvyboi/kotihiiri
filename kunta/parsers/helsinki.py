"""Page parsers for paatokset.hel.fi (PLAN.md §7.1). Pure functions: HTML in, plain data out.

Structure recorded in PLAN.md §16 (S1, S6). The parsers key on visible text and URL shapes, not
on CSS classes.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from ..htmlblocks import Block, Link, all_links, blocks, iframe_srcs
from ..models import Attachment, AttachmentKind, Section, SectionType, Stage
from ..text import classify_heading, collapse_ws, strip_pii

BASE = "https://paatokset.hel.fi"
BODY_HREF = re.compile(r"^https://paatokset\.hel\.fi/fi/paattajat/([a-z0-9-]+)/?$")
BODY_WORDS = re.compile(r"valtuusto|hallitus|lautakunta|jaosto|johtokunta|toimikunta", re.IGNORECASE)
NOT_BODIES = {"lautakunnat-ja-johtokunnat"}
DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
LISTING_LABEL = re.compile(r"^(Esityslista|Pöytäkirja|Päätöstiedote)\s+(\d+)\s*[-/]\s*(\d{4})", re.IGNORECASE)
AGENDA_ROW = re.compile(r"^(\d+)\.\s*(?:/\s*(\d+)\s*§)?\s*(.+)$")
ITEM_HREF = re.compile(r"^https://paatokset\.hel\.fi/fi/asia/[^/?#]+")
ORD_LINE = re.compile(r"^(\d+)\.\s*/\s*(\d+)\s*§$")
CASE_NUMBER = re.compile(r"\bHEL \d{4}-\d{6}\b")
HISTORY_HEAD = re.compile(r"^.+\s\d{1,2}\.\d{1,2}\.\d{4}\s*§\s*\d+")
LOAD_ERROR = ("Virhe päätöstä ladattaessa", "Something went wrong loading decision")

# Headings that open a top-level part of an item page.
KNOWN_SECTIONS = {
    "päätös",
    "käsittely",
    "äänestystulokset",
    "päätösehdotus",
    "esitys",
    "esittelijän perustelut",
    "perustelut",
    "päätöshistoria",
    "muutoksenhaku",
    "esittelijä",
    "lisätietojen antaja",
    "lisätiedot",
    "liitteet",
    "liitteet (pdf)",
    "oheismateriaali",
    "pöytäkirjalausuma",
    "pöytäkirjalausumat",
    "eriävä mielipide",
    "eriävät mielipiteet",
    "tiedoksi",
}
PAGE_CHROME = {"sanat tai yhteystieto hukassa?", "jaa", "helsingin kaupunki", "ota yhteyttä"}
NOISE_LINES = re.compile(
    r"^(Sulje alue:?.*|Avaa kaikki|Katso äänestystulos taulukkona|Asialla on uudempia käsittelyjä.*|"
    r"Try again\.?|Kokouksen muut asiat|Lataa tulostusversio.*)$",
    re.IGNORECASE,
)


def _strip_query(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _no_fragment(url: str) -> str:
    return url.split("#", 1)[0]


def parse_date(text: str) -> dt.date | None:
    m = DATE.search(text)
    return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


# -- bodies -------------------------------------------------------------------------------


def parse_body_links(html: str) -> dict[str, str]:
    """slug → name for every decision-making body linked from a page (menu included)."""
    out: dict[str, str] = {}
    for link in all_links(html, BASE):
        m = BODY_HREF.match(link.href)
        if not m or m.group(1) in NOT_BODIES:
            continue
        name = re.sub(r"\s*\(.*?\)\s*$", "", link.text).strip()
        if name and BODY_WORDS.search(name):
            out.setdefault(m.group(1), name)
    return out


def parse_body_name(html: str) -> str | None:
    for b in blocks(html, BASE):
        if b.kind == "h1":
            return b.text
    return None


# -- meeting listing ----------------------------------------------------------------------


@dataclass
class ListingRow:
    code: str
    label: str  # Esityslista | Pöytäkirja
    number: int
    year: int
    date: dt.date
    url: str


def parse_listing(html: str, slug: str) -> list[ListingRow]:
    href_rx = re.compile(
        rf"^https://paatokset\.hel\.fi/fi/paattajat/{re.escape(slug)}/asiakirjat/([0-9A-Za-z-]+)"
    )
    rows: list[ListingRow] = []
    pending: tuple[str, str, int, int, str] | None = None
    for b in blocks(html, BASE):
        for link in b.links:
            m = href_rx.match(link.href)
            lm = LISTING_LABEL.match(link.text)
            if m and lm:
                pending = (m.group(1), lm.group(1).capitalize(), int(lm.group(2)), int(lm.group(3)),
                           _no_fragment(link.href))  # fmt: skip
                break
        if pending and b.text.lower().startswith("päätöksentekopäivä") and (d := parse_date(b.text)):
            code, label, number, year, url = pending
            rows.append(ListingRow(code, label, number, year, d, url))
            pending = None
    return rows


# -- meeting page ---------------------------------------------------------------------------


@dataclass
class AgendaRow:
    ordinal: int
    pykala: int | None
    title: str
    url: str


@dataclass
class MeetingPage:
    stage: Stage
    date: dt.date | None
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = None
    rows: list[AgendaRow] = field(default_factory=list)
    print_pdf: str | None = None
    transcript_pdf: str | None = None
    video_url: str | None = None


def parse_meeting(html: str) -> MeetingPage:
    bl = blocks(html, BASE)
    h1 = next((b.text for b in bl if b.kind == "h1"), "")
    first = h1.split(" ", 1)[0].lower()
    stage = Stage.minutes if first == "pöytäkirja" else Stage.agenda
    page = MeetingPage(stage=stage, date=parse_date(h1))

    in_bulletin = False
    bulletin_lines = 0
    seen: set[int] = set()
    for b in bl:
        if b.is_heading:
            in_bulletin = b.text.lower().startswith("päätöstiedote")
            continue
        if in_bulletin and b.kind == "text":
            bulletin_lines += 1
        low = b.text.lower()
        if low.startswith("kokousaika"):
            # "09.09.2026 - 18:00": the date's "09.09" also looks like a time; keep hh:mm with a colon
            times = [f"{int(h):02d}:{mm}" for h, mm in re.findall(r"(\d{1,2}):(\d{2})", b.text)]
            if times:
                page.start_time = times[0]
            if len(times) > 1:
                page.end_time = times[1]
        elif low.startswith("kokouspaikka"):
            page.location = b.text.split(":", 1)[1].strip() or None
        for link in b.links:
            lt = link.text.lower()
            if ITEM_HREF.match(link.href) and (m := AGENDA_ROW.match(link.text)):
                ordinal = int(m.group(1))
                if ordinal not in seen:
                    seen.add(ordinal)
                    page.rows.append(
                        AgendaRow(
                            ordinal, int(m.group(2)) if m.group(2) else None, m.group(3).strip(), link.href
                        )
                    )
            elif "tulostusversio" in lt and link.href.lower().endswith(".pdf"):
                page.print_pdf = page.print_pdf or link.href
            elif "keskustelupöytäkirja" in lt and link.href.lower().endswith(".pdf"):
                page.transcript_pdf = page.transcript_pdf or link.href
            if "icareus.com" in link.href:
                page.video_url = page.video_url or link.href
    if page.video_url is None:
        page.video_url = next((s for s in iframe_srcs(html, BASE) if "icareus.com" in s), None)
    # A decision bulletin with entries (not just the "published after the meeting" notice).
    if stage == Stage.agenda and bulletin_lines > 2:
        page.stage = Stage.decisions
    page.rows.sort(key=lambda r: r.ordinal)
    return page


# -- item page ------------------------------------------------------------------------------


@dataclass
class ItemPage:
    title: str | None = None
    ordinal: int | None = None
    pykala: int | None = None
    case_number: str | None = None
    presenter: str | None = None
    sections: list[Section] = field(default_factory=list)
    deliberation_lines: list[str] = field(default_factory=list)
    vote_blocks: list[Block] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    load_error: bool = False

    def has_decision(self) -> bool:
        return any(s.type == SectionType.decision for s in self.sections)


def _section_text(lines: list[str]) -> str:
    return collapse_ws(strip_pii("\n\n".join(lines)))


def parse_item(html: str) -> ItemPage:
    bl = blocks(html, BASE)
    page = ItemPage(load_error=any(e in html for e in LOAD_ERROR))

    # Everything after the decision's ordinal line belongs to the decision; before it are the case
    # title, case number and decision picker.
    start = 0
    for i, b in enumerate(bl):
        if b.kind == "text" and (m := ORD_LINE.match(b.text)):
            page.ordinal, page.pykala = int(m.group(1)), int(m.group(2))
            prev = next((x for x in reversed(bl[:i]) if x.is_heading), None)
            page.title = prev.text if prev else None
            start = i + 1
            break
    for b in bl:
        if m := CASE_NUMBER.search(b.text):
            page.case_number = m.group(0)
            break
    if page.title is None:
        page.title = next((b.text for b in bl if b.kind == "h1"), None)

    mode: str | None = None  # current top-level part
    kind: SectionType | None = None
    heading: str | None = None
    lines: list[str] = []
    history: list[Section] = []
    hist_heading: str | None = None
    hist_lines: list[str] = []
    hist_skip = False
    presenter_lines: list[str] = []

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
        text = b.text
        low = text.lower()
        if b.kind == "text" and NOISE_LINES.match(text):
            continue
        if any(e in text for e in LOAD_ERROR):
            continue

        if mode == "history":
            if b.is_heading and HISTORY_HEAD.match(text):
                close_history()
                hist_heading, hist_skip = text, False
                continue
            if b.is_heading and (low == "muutoksenhaku" or low in PAGE_CHROME or low.startswith("liitteet")):
                close_history()
                mode = None
            elif b.is_heading:
                hist_skip = classify_heading(text) is None
                if not hist_skip:
                    hist_lines.append(text)
                continue
            else:
                if not hist_skip and b.kind == "text":
                    hist_lines.append(text)
                elif not hist_skip and b.kind == "table":
                    hist_lines.extend(" | ".join(r) for r in b.rows)
                continue

        if b.is_heading and low in PAGE_CHROME:
            close_section()
            mode = "chrome"
            continue
        if b.is_heading and low in KNOWN_SECTIONS:
            close_section()
            heading = text
            if low == "päätöshistoria":
                mode, hist_heading, hist_lines = "history", None, []
            elif low == "äänestystulokset":
                mode = "votes"
            elif low == "esittelijä":
                mode = "presenter"
            elif low.startswith("liitteet") or low == "oheismateriaali":
                mode = "attachments_supp" if low == "oheismateriaali" else "attachments"
            else:
                kind = classify_heading(text)
                mode = "section" if kind is not None else "drop"
            continue

        if mode == "section":
            if b.kind == "table":
                lines.extend(" | ".join(r) for r in b.rows)
            else:
                lines.append(text)
                if kind == SectionType.deliberation and b.kind in ("text", "h4", "h5", "h6"):
                    page.deliberation_lines.append(text)
        elif mode == "votes":
            page.vote_blocks.append(b)
        elif mode == "presenter" and b.kind == "text":
            presenter_lines.append(text)
        elif mode in ("attachments", "attachments_supp"):
            for link in b.links:
                if link.href.lower().endswith(".pdf") and "tulostusversio" not in link.text.lower():
                    page.attachments.append(
                        Attachment(
                            title=link.text or link.href.rsplit("/", 1)[-1],
                            url=link.href,
                            kind=AttachmentKind.supplementary
                            if mode == "attachments_supp"
                            else AttachmentKind.attachment,
                        )
                    )
    close_section()
    if mode == "history":
        close_history()
    page.sections.extend(history)

    presenter = [p for p in presenter_lines if p.lower() not in ("titteli",)]
    if presenter:
        page.presenter = strip_pii(
            ", ".join(reversed(presenter)) if len(presenter) == 2 else ", ".join(presenter)
        )
    seen: set[str] = set()
    page.attachments = [a for a in page.attachments if not (a.url in seen or seen.add(a.url))]
    return page


def links_with(html: str, needle: str) -> list[Link]:
    return [link for link in all_links(html, BASE) if needle in link.href]
