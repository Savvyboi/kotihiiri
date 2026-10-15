"""Page parsers for CaseM / CloudNC at tampere.cloudnc.fi (PLAN.md §7.3). Pure functions: HTML in,
plain data out.

Structure recorded on 2026-10-13 (PLAN.md §16, S2):

- `/fi-FI/Toimielimet`: the side navigation lists every body as `Toimielimet/{Slug}`; discontinued
  bodies are prefixed "Z/";
- `/fi-FI/Toimielimet/{Slug}`: "Esityslista" links for upcoming meetings, after a line
  "{place} dd.mm.yyyy klo.17.00", then "Pöytäkirjat {year}" with links "Kokous d.m.yyyy Pöytäkirja",
  all to `/fi-FI/Toimielimet/{Slug}/Kokous_{dmyyyy}`;
- meeting page: h1 "{Body}, kokous d.m.yyyy", an h2 "Pöytäkirja"/"Esityslista" with the "Lataa"
  PDF link, item links "§ n {title}" to `/fi-FI/content/{itemId}/{meetingId}`, and "Kokouksen
  osallistujat" with h3 groups (Paikalla olleet jäsenet, Muut paikalla olleet, Poissa; at agenda
  stage only Osallistujat), one person per line as "Surname First[, note] - Role";
- item page: h2 "§ n {title}" (confidential items add "(Salassa pidettävä)" and the legal basis),
  the case number in `div.native-id`, earlier bodies' handling in an accordion under "Aikaisempi
  käsittely", the preparers under "Valmistelija", this body's parts in `div.sorteddivs`
  (Perustelut, Päätösehdotus / Päätösehdotus oli with "Esittelijä", Päätös), "Kokouskäsittely" in
  `#Content_Content_pnlEventhandling`, votes in `div.votingResults` (see votes_casem), recipients
  in `div.inform`, attachments in `div.topicAttacmentList` under an h2 caption.

Contact blocks (Valmistelijan yhteystiedot, Lisätietoja päätöksestä) and appeal instructions are
dropped.
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
from selectolax.lexbor import LexborNode as Node

from ..htmlblocks import blocks, clean
from ..models import Attachment, AttachmentKind, Section, SectionType, Stage
from ..text import classify_heading, collapse_ws, strip_pii

BASE = "https://tampere.cloudnc.fi"
ROOT = BASE + "/fi-FI/"
# Relative links resolve against the host being parsed; adapters set it with `base_url(...)`.
_ROOT: ContextVar[str] = ContextVar("casem_root", default=ROOT)


@contextmanager
def base_url(base: str) -> Iterator[None]:
    """Resolve links against `{base}/fi-FI/` (one CloudNC site per municipality, §18.1)."""
    token = _ROOT.set(base.rstrip("/") + "/fi-FI/")
    try:
        yield
    finally:
        _ROOT.reset(token)


DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
BODY_HREF = re.compile(r"/Toimielimet/([^/?#]+)/?$")
MEETING_HREF = re.compile(r"/Toimielimet/([^/?#]+)/(Kokous_[^/?#]+)/?$")
ITEM_HREF = re.compile(r"/fi-FI/content/(\d+)/(\d+)/?$")
DOWNLOAD_HREF = re.compile(r"^https?://[^/]+/download/")
PYKALA_TITLE = re.compile(r"^§\s*(\d+)\s*(.*)$")
START_TIME = re.compile(r"klo\.?\s*(\d{1,2})[.:](\d{2})", re.IGNORECASE)
CONFIDENTIAL = re.compile(r"\s*\((salassa pidettävä)\)\s*$", re.IGNORECASE)
ATTACHMENT_SIZE = re.compile(
    r"\s*\((?:pdf|docx?|xlsx?|pptx?|zip|[a-z]{2,4}),\s*[\d\s.,]+\s*[km]?t\)\s*$", re.I
)


def parse_date(text: str) -> dt.date | None:
    m = DATE.search(text)
    return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _text(node: Node | None) -> str:
    return clean(node.text(deep=True, separator=" ")) if node is not None else ""


def _content(html: str) -> str:
    """The page's content area. ASP.NET wraps the whole page in a <form>, which `blocks` skips."""
    node = HTMLParser(html).css_first("#contentAreaDiv")
    return (node.html or html) if node is not None else html


def _href(node: Node, base: str | None = None) -> str:
    return urljoin(base or _ROOT.get(), (node.attributes.get("href") or "").strip())


# -- bodies -------------------------------------------------------------------------------


def parse_bodies(html: str) -> dict[str, str]:
    """Body slug (as the site spells it) → name as printed, from `/fi-FI/Toimielimet`."""
    tree = HTMLParser(html)
    nav = tree.css_first("#Content_sidenaviArea") or tree.body
    out: dict[str, str] = {}
    for a in nav.css("a[href]") if nav is not None else []:
        m = BODY_HREF.search(_href(a))
        name = _text(a)
        if m and name:
            out.setdefault(m.group(1), name)
    return out


def body_name(name: str) -> str:
    """ "Z/Sosiaali- ja terveyslautakunta" → the name without the discontinued-body marker, so the
    body keeps its id when the site retires it."""
    return re.sub(r"^Z/\s*", "", name).strip()


# -- meeting listing ----------------------------------------------------------------------


@dataclass
class ListingRow:
    meeting_key: str  # "Kokous_10112025"
    date: dt.date
    stage: Stage
    url: str
    start_time: str | None = None
    location: str | None = None


def parse_meetings(html: str) -> list[ListingRow]:
    """Every meeting a body page lists. Minutes links carry the date ("Kokous 14.9.2026
    Pöytäkirja"); an upcoming agenda's "Esityslista" link follows a line with place, date and time.
    The URL's digits are not parsed: "Kokous_1492026" is ambiguous without separators."""
    rows: dict[str, ListingRow] = {}
    previous = ""
    for b in blocks(_content(html), _ROOT.get()):
        for link in b.links:
            m = MEETING_HREF.search(link.href)
            if not m:
                continue
            label = link.text.lower()
            if "pöytäkirja" in label and (date := parse_date(link.text)):
                rows.setdefault(m.group(2), ListingRow(m.group(2), date, Stage.minutes, link.href))
            elif "esityslista" in label:
                context = b.text if parse_date(b.text) else previous
                date = parse_date(context)
                if date is None:
                    continue
                row = ListingRow(m.group(2), date, Stage.agenda, link.href)
                if t := START_TIME.search(context):
                    row.start_time = f"{int(t.group(1)):02d}:{t.group(2)}"
                place = DATE.split(context, maxsplit=1)[0].strip(" ,")
                row.location = place or None
                rows.setdefault(m.group(2), row)
        if not b.links:
            previous = b.text
    return list(rows.values())


# -- meeting page -------------------------------------------------------------------------


@dataclass
class AgendaRow:
    ordinal: int  # position on the page, 1-based
    pykala: int | None
    title: str
    url: str
    item_key: str  # "{itemId}/{meetingId}"


@dataclass
class Participant:
    name: str
    role: str
    present: bool
    note: str | None = None
    member: bool = False


@dataclass
class MeetingPage:
    stage: Stage | None
    date: dt.date | None
    minutes_pdf: str | None = None
    rows: list[AgendaRow] = field(default_factory=list)
    participants: list[Participant] = field(default_factory=list)


GROUPS = {
    "paikalla olleet jäsenet": (True, True),
    "muut paikalla olleet": (True, False),
    "poissa": (False, False),
    "poissa olleet": (False, False),
    "poissa olleet jäsenet": (False, True),
}


def _participant(line: str, present: bool, member: bool) -> Participant | None:
    """ "Kummola Kalervo, puheenjohtajana 9:00-13:00 - Puheenjohtaja", "Heikkilä Lasse - Varajäsen",
    "Ovaska Jouni, 9:00-15:25 ja 17:30-19:10"."""
    line = clean(line.replace("​", ""))
    if not line:
        return None
    head, _, role = line.partition(" - ")
    name, _, note = head.partition(",")
    role = role.strip() or ("jäsen" if member else "")
    return Participant(name.strip(), role, present, note.strip() or None, member)


def parse_meeting(html: str) -> MeetingPage:
    tree = HTMLParser(html)
    main = tree.css_first("div.article-content") or tree.body
    h1 = _text(main.css_first("h1")) if main is not None else ""
    page = MeetingPage(stage=None, date=parse_date(h1))
    for h2 in main.css("h2") if main is not None else []:
        label = _text(h2).lower()
        if "pöytäkirja" in label or "esityslista" in label:
            page.stage = Stage.minutes if "pöytäkirja" in label else Stage.agenda
            for a in h2.css("a[href]"):
                if DOWNLOAD_HREF.match(_href(a)) and "lataa" in _text(a).lower():
                    page.minutes_pdf = _href(a)
            break

    seen: set[str] = set()
    for a in main.css("a[href]") if main is not None else []:
        href = _href(a)
        m = ITEM_HREF.search(href)
        text = _text(a)
        if not m or not text:
            continue
        key = f"{m.group(1)}/{m.group(2)}"
        if key in seen:
            continue
        seen.add(key)
        p = PYKALA_TITLE.match(text)
        pykala, title = (int(p.group(1)), p.group(2).strip()) if p else (None, text)
        page.rows.append(AgendaRow(len(page.rows) + 1, pykala, title, href.split("?")[0], key))

    group: tuple[bool, bool] | None = None
    in_participants = False
    for b in blocks(_content(html), _ROOT.get()):
        low = b.text.lower().strip()
        if b.kind == "h2":
            in_participants = low.startswith("kokouksen osallistujat")
            group = None
            continue
        if not in_participants:
            continue
        if b.kind == "h3":
            group = GROUPS.get(low)
            continue
        if group is not None and b.kind == "text" and (p := _participant(b.text, *group)):
            page.participants.append(p)
    return page


# -- item page ----------------------------------------------------------------------------


@dataclass
class ItemPage:
    title: str | None = None
    pykala: int | None = None
    confidential: bool = False
    case_number: str | None = None
    presenter: str | None = None
    preparers: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    deliberation_lines: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    item_pdf: str | None = None
    votes_html: str | None = None

    def has_decision(self) -> bool:
        return any(s.type == SectionType.decision for s in self.sections)


PART_HEADINGS: dict[str, SectionType | None] = {
    "perustelut": SectionType.background,
    "päätösehdotus": SectionType.proposal,
    "päätösehdotus oli": SectionType.proposal,
    "esitys": SectionType.proposal,
    "päätös": SectionType.decision,
    "kokouskäsittely": SectionType.deliberation,
    "pöytäkirjamerkintä": SectionType.statement,
    "eriävä mielipide": SectionType.dissent,
    "tiedoksi": None,  # recipients
    "valmistelijan yhteystiedot": None,
    "lisätietoja päätöksestä": None,
    "muutoksenhaku": None,
}


def _lines(node: Node) -> list[str]:
    """Text lines of a part, without its h3 heading."""
    return [b.text for b in blocks(node.html or "", _ROOT.get()) if not b.is_heading and b.text]


def _section_text(lines: list[str]) -> str:
    return collapse_ws(strip_pii("\n\n".join(lines)))


def _people(node: Node) -> list[str]:
    """The "Valmistelija" / "Esittelijä" list after a label paragraph: "Linnamaa Reija, Johtaja"."""
    return [ln for ln in (b.text for b in blocks(node.html or "", _ROOT.get())) if ln]


def _labelled(node: Node, label: str) -> tuple[list[Node], list[str]]:
    """Paragraphs reading `label` in `node` (not inside the history accordion) and the people
    listed in the `div.item` after each."""
    found: list[Node] = []
    people: list[str] = []
    for p in node.css("p"):
        if _text(p).lower() != label or _in_history(p):
            continue
        found.append(p)
        nxt = p.next
        while nxt is not None and nxt.tag in ("-text", "#text"):
            nxt = nxt.next
        if nxt is not None and nxt.tag == "div":
            found.append(nxt)
            people.extend(_people(nxt))
    return found, people


def _in_history(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.attributes.get("id") == "history-topics-accordion":
            return True
        parent = parent.parent
    return False


def parse_item(html: str) -> ItemPage:
    tree = HTMLParser(html)
    main = tree.css_first("div.article-content")
    page = ItemPage()
    if main is None:
        return page

    for a in main.css("a#Content_Content_hlTopicAttachment[href]"):
        page.item_pdf = _href(a)
    if (h2 := main.css_first("div.subheader h2")) is not None:
        heading = _text(h2)
        if m := CONFIDENTIAL.search(heading):
            page.confidential = True
            heading = heading[: m.start()]
        if p := PYKALA_TITLE.match(heading):
            page.pykala, page.title = int(p.group(1)), p.group(2).strip() or None
        else:
            page.title = heading or None
        if page.confidential and page.title:
            page.title = f"{page.title} (Salassa pidettävä)"
    page.case_number = _text(main.css_first("div.native-id")) or None

    # Preparers and presenter of this body (the history accordion has its own).
    _, preparers = _labelled(main, "valmistelija")
    page.preparers = [strip_pii(p.split(",", 1)[0]).strip() for p in preparers]
    page.preparers = [p for p in page.preparers if p]

    for div in main.css("div.sorteddivs > div"):
        heading = _text(div.css_first("h3"))
        kind = PART_HEADINGS.get(heading.lower().rstrip(":"), classify_heading(heading))
        if kind is None:
            continue
        presenter_nodes, presenters = _labelled(div, "esittelijä")
        if presenters and not page.presenter:
            page.presenter = strip_pii(presenters[0]).strip(" ,") or None
        for n in presenter_nodes:
            n.decompose()
        text = _section_text(_lines(div))
        if text:
            page.sections.append(Section(type=kind, heading=heading or None, text=text))

    if (handling := main.css_first("#Content_Content_pnlEventhandling")) is not None:
        page.deliberation_lines = [strip_pii(ln) for ln in _lines(handling)]
        text = _section_text(page.deliberation_lines)
        if text:
            page.sections.append(Section(type=SectionType.deliberation, heading="Kokouskäsittely", text=text))

    if (votes := main.css_first("div.votingResults")) is not None:
        page.votes_html = votes.html

    for group in main.css("#history-topics-accordion div.accordion-group"):
        heading = _text(group.css_first("div.accordion-heading"))
        inner = group.css_first("div.accordion-inner")
        if inner is None:
            continue
        for n in inner.css("span.history-draftsmans"):
            n.decompose()  # preparers with their contact details
        text = _section_text(_lines(inner))
        if heading and text:
            page.sections.append(Section(type=SectionType.history, heading=heading, text=text))

    page.attachments = _attachments(main)
    return page


def _attachments(main: Node) -> list[Attachment]:
    out: list[Attachment] = []
    seen: set[str] = set()
    for box in main.css("div.topicAttacmentList"):
        caption = _text(box.css_first("h2")).lower()
        kind = AttachmentKind.supplementary if "oheismateriaal" in caption else AttachmentKind.attachment
        for a in box.css("a[href]"):
            href = _href(a)
            if not DOWNLOAD_HREF.match(href) or href in seen:
                continue  # read-aloud links point to docreader.readspeaker.com
            title = ATTACHMENT_SIZE.sub("", _text(a)).strip()
            if title:
                seen.add(href)
                out.append(Attachment(title=title, url=href, kind=kind))
    return out
