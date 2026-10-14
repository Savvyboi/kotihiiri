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
            if url and re.search(r"kansilehti", title, re.IGNORECASE):
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

# "Aika 21.9.2026 klo 18.05–23.18", "Aika 17.11.2025 klo 13.00- 18.11.2025 klo 0.22"
SESSION = re.compile(
    r"^Aika\s+(\d{1,2}\.\d{1,2}\.\d{4})\s+klo\s+(\d{1,2})[.:](\d{2})"
    r"(?:\s*[–-]\s*(?:\d{1,2}\.\d{1,2}\.\d{4}\s+klo\s+)?(\d{1,2})[.:](\d{2}))?"
)
PLACE = re.compile(r"^Paikka\s+(.+)$")
_NAME = r"(?:(?:el|af|von|de|van)\s+)?[A-ZÅÄÖ][^,()]*?"
# A note in brackets after the mark: "(klo 18.05-21.03 § 1-8)", or cut by the line end or the
# next column's entry: "(pj § 1-6, 13.00- Lahti Timo x" (the rest of the note is on the next line).
NOTE = rf"\([^()]*?(?:\)|(?=\s{_NAME}\s(?:x|-)(?:\s|$))|$)"
ENTRY = re.compile(
    rf"(?P<name>{_NAME})(?:,\s*(?P<role>[^()]*?))?\s+(?P<mark>x|-)(?=\s|$)(?:\s*(?P<note>{NOTE}))?"
)
GROUPS = [
    (re.compile(r"^Jäsenet\s+Läsnä"), "jäsen"),
    (re.compile(r"^Varajäsenet\s+Läsnä"), "varajäsen"),
    (re.compile(r"^Kaupunginhallituksen jäsenet\b"), "kaupunginhallituksen jäsen"),
    (re.compile(r"^Nuorisovaltuuston\b"), "nuorisovaltuuston edustaja"),
    (re.compile(r"^Muut osallistujat\b"), "muu osallistuja"),
]
COVER_END = re.compile(r"^(Kokouksen laillisuus|Allekirjoitukset|Pöytäkirjan tarkastus|Käsitellyt asiat)")


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


def parse_cover(lines: list[str]) -> Cover:
    cover = Cover()
    group: str | None = None
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or re.fullmatch(r"Nro \d+/\d{4}", line):
            continue
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
            continue
        if group is None or re.match(r"^[\d§]", line):  # "22.10 § 1-9)": the rest of a note
            continue
        for m in ENTRY.finditer(line):
            name = m.group("name").strip()
            if not re.match(r"^[A-ZÅÄÖa-zåäö]", name) or name.lower() in ("läsnä", "jäsenet"):
                continue
            role = (m.group("role") or "").strip(" ,") or group
            note = m.group("note")
            cover.participants.append(
                Participant(
                    name=name,
                    role=role,
                    present=m.group("mark") == "x",
                    note=_note(note),
                )
            )
    return cover


# -- item document ------------------------------------------------------------------------

DIARY = re.compile(r"^[A-ZÅÄÖ]{1,4}/\d+/[\d.]+/\d{4}$")
INITIALS = re.compile(r"^[A-ZÅÄÖ][A-Za-zÅÄÖåäö]{0,3}(?:/[A-ZÅÄÖ][A-Za-zÅÄÖåäö]{0,3})*$")
BODY_WORD = r"(?:valtuusto|hallitus|lautakun\w*|jaosto|johtokunta|toimikunta|neuvosto)"
BLOCK = re.compile(
    rf"^(?P<body>[A-ZÅÄÖ][\wÅÄÖåäö-]*(?:\s+[\wÅÄÖåäö-]+){{0,5}}?\s*{BODY_WORD}[\wåäö]*(?:\s+[\wåäö-]+)?)"
    r"\s+(?P<date>\d{1,2}\.\d{1,2}\.\d{4})\s+§\s*(?P<n>\d+)$",
    re.IGNORECASE,
)
PROPOSAL = re.compile(r"^(?:[\wÅÄÖåäö-]+\s+){0,5}esitys\s*:$|^Esitys\s*:$", re.IGNORECASE)
HEADINGS = {
    "käsittely": SectionType.deliberation,
    "päätös": SectionType.decision,
    "päätösehdotus": SectionType.proposal,
}
ATTACHMENTS = re.compile(r"^(Liite|Liitteet|Oheismateriaali)\s*:", re.IGNORECASE)
END = re.compile(r"^(Muutoksenhakuohje|Lisätiedot|Lisätietoja|Tiedoksi)\b", re.IGNORECASE)
RULE = re.compile(r"^_{3,}$")
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
            date = parse_date(m.group("date"))
            assert date is not None
            doc.blocks.append(Block(body=m.group("body"), date=date, pykala=int(m.group("n"))))
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
        for kind, heading, lines in block_parts(block):
            if kind == SectionType.deliberation:
                deliberation = list(lines)
            if kind == SectionType.decision:
                lines, stmts = _split_statements(lines)
                for skind, slines in stmts:
                    if text := _text(slines):
                        statements.append(Section(type=skind, text=text))
            if text := _text(lines):
                sections.append(Section(type=kind, heading=heading or None, text=text))
    return sections, statements, deliberation


# -- motions and votes in the Käsittely prose ---------------------------------------------

_NUM = r"(\d+|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + ")"
NAMEWORD = r"(?:el|af|von|de|van)\s+[A-ZÅÄÖ][\w'’-]+|[A-ZÅÄÖ][\w'’-]+"
PERSON = rf"(?:{NAMEWORD})(?:\s+(?:{NAMEWORD})){{0,3}}"
MOTION = re.compile(
    rf"(?P<prop>{PERSON})\s+(?P<verb>teki|esitti|ehdotti)\s+"
    rf"(?:(?P<sec>(?:[a-zåäö]+\s+){{0,3}}{PERSON})\s+kannattamana\s*,?\s*)?"
    r"(?P<rest>.*?)(?=(?:Puheenjohtaja|Asian käsittelyn aikana|Käsittelyn aikana|Valtuutettu|"
    r"Kaupunginhallituksen jäsen|_{3,})|$)",
    re.DOTALL,
)
# "… seuraavan muutosesityksen[, joka raukesi kannattamattomana]:" introduces the motion's text
INTRO = re.compile(
    r"^.*?(?:muutosesityksen|esityksen|ehdotuksen|lisäyksen)\s*"
    r"(?:,\s*joka\s+raukesi\s+kannattamattomana)?\s*:\s*"
)
UNSECONDED = re.compile(r"raukesi\s+kannattamattomana", re.IGNORECASE)
PROPOSITION = re.compile(
    r"he,\s+jotka\s+kannattavat\s+(?P<jaa>.+?),\s+äänestävät\s+jaa,?\s+ja\s+he,\s+(?:jotka|ketkä)\s+"
    r"kannattavat\s+(?P<ei>.+?),\s+äänestävät\s+ei",
    re.IGNORECASE | re.DOTALL,
)
_PAREN = r"(?:\s*\((?P<{0}>[^)]*)\))?"
RESULT = re.compile(
    rf"Äänestyksessä\s+annettiin\s+(?P<j>{_NUM})\s+jaa-ään\w*{_PAREN.format('jn')}"
    rf"\s*(?:,|ja)?\s*(?P<e>{_NUM})\s+ei-ään\w*{_PAREN.format('en')}"
    rf"(?:\s*(?:,|ja)\s*(?P<t>{_NUM})\s+tyhj\w*(?:-ään\w*)?{_PAREN.format('tn')})?",
    re.IGNORECASE,
)


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


def _motions_at(text: str) -> list[tuple[int, Motion]]:
    out = []
    for m in MOTION.finditer(text):
        prop = _person(m.group("prop"))
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
    return out


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
    return [n.strip() for n in re.split(r",|\s+ja\s+", text) if n.strip()]


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


def parse_prose(lines: list[str]) -> list[TwebProse]:
    text = _flat(lines)
    out = []
    props = list(PROPOSITION.finditer(text))
    for m in RESULT.finditer(text):
        prop = next((p for p in reversed(props) if p.end() <= m.start()), None)
        # a proposition belongs to the first result after it
        if prop is not None and any(o.prop_end == prop.end() for o in out):
            prop = None
        e = text.find(". ", m.end())
        sentence = text[m.start() : len(text) if e < 0 else e + 1].strip()
        pv = TwebProse(
            a=_n(m.group("j")),
            b=_n(m.group("e")),
            tyhja=_n(m.group("t")) if m.group("t") else 0,
            sentence=sentence,
            jaa_label=_short_label(prop.group("jaa")) if prop else "",
            ei_label=_short_label(prop.group("ei")) if prop else "",
            names={
                c: _names(m.group(k))
                for c, k in ((Choice.jaa, "jn"), (Choice.ei, "en"), (Choice.tyhja, "tn"))
                if m.group(k)
            },
            prop_end=prop.end() if prop else -1,
            start=m.start(),
        )
        out.append(pv)
    return out


def parse_case(lines: list[str]) -> tuple[list[Motion], list[TwebProse]]:
    """Motions and votes of one Käsittely. A vote decides the latest motion before it whose
    proposer the Ei side names in the genitive ("valtuutettu Eerolan … muutosesitystä")."""
    text = _flat(lines)
    placed = _motions_at(text)
    prose = parse_prose(lines)
    for pv in prose:
        gen = pv.ei_label.split()[0] if pv.ei_label else ""
        before = [mo for pos, mo in placed if pos < pv.start]
        for mo in reversed(before):
            surname = mo.proposer_ref.raw.split()[-1]
            if gen and _is_genitive(gen, surname):
                mo.outcome = Outcome.adopted if pv.b > pv.a else Outcome.rejected
                break
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
