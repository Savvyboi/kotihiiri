"""paatokset.turku.fi (PLAN.md §7.6).

The site is a single-page app over a public JSON API at `/api` (probed 2026-11-15 from a home
connection; the HTML pages are all the same empty shell). One call per step:

    /api/toimielimet                       bodies: kaupunginvaltuusto, kaupunginhallitus, lautakunnat[],
                                           seudullisetLautakunnat[], vaikuttajaRyhmat[],
                                           lakkautetutToimielimet[]; each {nimi, nimi_se, lyhenne,
                                           loppuPvm, tyyppi, kieli, vast_osapuoli}
    /api/toimielin/{lyhenne}/paatosvuodet  ["2026", "2025", …]
    /api/toimielin/{lyhenne}?vuosi=YYYY    [{tktviiteId, tktviiteTyyppi (pk minutes | el agenda),
                                           kokPvm, pkNro, pkVuosi, tyyppi}]
    /api/poytakirja/{tktviiteId}           {poytakirja: {kokPvm, kokKlo, kokPaatKlo, kokPaikka, …},
                                           pykalat: [{tktviiteId, tktviiteTyyppi, pykNro, tktNimi,
                                           html, diJnro, diVuosi, elasiaNro, salausperuste}]}
    /api/lasnaolotiedot/{tktviiteId}       [{lasolNimi, tehtava, …}]
    /api/liitteet/{item tktviiteId}        {"Kv-186": [{tktNimi, tktviiteTyyppi, suojattu, html}], …}

An item's `html` carries the whole case history: one `<p>Kh § 315</p>` marker per handling, each
followed by `div.XSDoc` blocks whose sections open with `<span class="ehdotuspaatos">Päätös</span>`.
The last marker of the meeting's own body is this meeting's handling; the earlier ones are history,
and the presenter's background text sits at the top of the first handling. Agenda items carry a
marker without a number (`<p>Kv § </p>`).

Council votes: the decision prose gives totals ("Suoritetussa koneäänestyksessä 56 valtuutettua
kannatti … ja 11 valtuutettua kannatti …") and the per-member list is the attachment
"Äänestyslistat / Omröstningsförteckningarna", a PDF with one page per vote:

    Äänestyslista / Omröstningsförteckning — Kaupunginvaltuusto 26.10.2026 klo 18:00
    Asia / Ärende 4 Ammatillisen koulutuksen yhtiöittäminen
    Äänestys / Omröstning 1
    Jaa / Ja Ehdotus / Förslag Kh
    Ei / Nej Muutos / Ändring Diop Paco (Ekman Johan)
    Jaa / Ja 56 … Poissa / Frånvarande 0
    Aalto-Setälä Matti KOK J Lindén Aki SDP J        (two columns: name, party, J/E/T/P)

"Asia" is the agenda number (`elasiaNro`), not the pykälä.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from ..htmlblocks import all_links, blocks, clean
from ..models import Attachment, AttachmentKind, Choice, Section, SectionType, Stage
from ..text import collapse_ws, strip_pii
from .votes_cloudmeeting import PdfVote, ProseVote

BASE = "https://paatokset.turku.fi"
API = "/api"

# -- bodies ---------------------------------------------------------------------------------

BODY_GROUPS = ("lautakunnat", "seudullisetLautakunnat", "vaikuttajaRyhmat", "lakkautetutToimielimet")
OPEN_ENDED = dt.date(3000, 1, 1)


@dataclass
class BodyRow:
    abbr: str  # lyhenne: Kv, Kh, Khkon …
    name: str
    name_sv: str | None
    lang: str
    counterpart: str | None  # vast_osapuoli: the other language's twin (Kv ↔ Sfm)
    active_to: dt.date | None


def route_slug(name: str) -> str:
    """The SPA's path for a body (its `Bt()`): "Kaupunginvaltuusto" → "kaupunginvaltuusto"."""
    s = name.lower().replace("ä", "a").replace("ö", "o").replace("å", "a")
    s = re.sub(r"[^a-zA-Z0-9\s]", "", s)
    return re.sub(r"\s+", "-", s)


def _date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_bodies(data: dict) -> list[BodyRow]:
    """Every body once. Swedish twins of Finnish bodies (Stadsfullmäktige ↔ Kaupunginvaltuusto,
    same documents) are left out; Swedish-only bodies (regional committees run in Swedish) stay."""
    raw: list[dict] = []
    for key in ("kaupunginvaltuusto", "kaupunginhallitus"):
        if isinstance(data.get(key), dict):
            raw.append(data[key])
    for key in BODY_GROUPS:
        raw.extend(r for r in data.get(key) or [] if isinstance(r, dict))
    abbrs = {r.get("lyhenne") for r in raw}
    out: dict[str, BodyRow] = {}
    for r in raw:
        abbr, name = (r.get("lyhenne") or "").strip(), clean(r.get("nimi") or "")
        if not abbr or not name or abbr in out:
            continue
        twin = r.get("vast_osapuoli")
        if r.get("kieli") == "sv" and twin and twin in abbrs:
            continue
        end = _date(r.get("loppuPvm"))
        out[abbr] = BodyRow(
            abbr=abbr,
            name=name,
            name_sv=clean(r.get("nimi_se") or "") or None,
            lang=r.get("kieli") or "fi",
            counterpart=twin,
            active_to=end if end and end < OPEN_ENDED else None,
        )
    return list(out.values())


# -- meetings -------------------------------------------------------------------------------


@dataclass
class MeetingRow:
    api_id: str
    date: dt.date
    stage: Stage
    number: str | None  # "9/2026"


def parse_meetings(data: list) -> list[MeetingRow]:
    rows = []
    for r in data or []:
        date = _date(r.get("kokPvm"))
        if not date or not r.get("tktviiteId"):
            continue
        kind = r.get("tktviiteTyyppi")
        if kind not in ("pk", "el"):
            continue
        nro, year = r.get("pkNro"), r.get("pkVuosi")
        rows.append(
            MeetingRow(
                api_id=str(r["tktviiteId"]),
                date=date,
                stage=Stage.minutes if kind == "pk" else Stage.agenda,
                number=f"{nro}/{year}" if nro and year else None,
            )
        )
    return rows


def _clock(value: str | None) -> str | None:
    """ "1800" → "18:00"."""
    if not value or not re.fullmatch(r"\d{3,4}", value.strip()):
        return None
    v = value.strip().zfill(4)
    return f"{v[:2]}:{v[2:]}"


@dataclass
class ItemRow:
    api_id: str
    kind: str  # pka decided item, ela agenda item, vpy1/vpy2 opening formalities
    title: str
    pykala: int | None
    agenda_no: str | None  # elasiaNro, the number the vote lists use
    case_number: str | None
    confidential: bool
    html: str


@dataclass
class MeetingPage:
    stage: Stage
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = None
    items: list[ItemRow] = field(default_factory=list)


SKIP_ITEM_KINDS = {"vo"}  # appeal instructions (valitusosoitus)


def parse_meeting(data: dict) -> MeetingPage:
    meta = data.get("poytakirja") or {}
    page = MeetingPage(
        stage=Stage.minutes if meta.get("tktviiteTyyppi") == "pk" else Stage.agenda,
        start_time=_clock(meta.get("kokKlo")),
        end_time=_clock(meta.get("kokPaatKlo")),
        location=(clean(meta.get("kokPaikka") or "").rstrip(".") or None),
    )
    for p in data.get("pykalat") or []:
        kind = p.get("tktviiteTyyppi") or ""
        if kind in SKIP_ITEM_KINDS or not p.get("tktviiteId"):
            continue
        nro = (p.get("pykNro") or "").strip()
        jnro, jyear = p.get("diJnro"), p.get("diVuosi")
        page.items.append(
            ItemRow(
                api_id=str(p["tktviiteId"]),
                kind=kind,
                title=clean((p.get("tktNimi") or "").replace("​", "")),
                pykala=int(nro) if nro.isdigit() else None,
                agenda_no=(p.get("elasiaNro") or None),
                case_number=f"{jnro}/{jyear}" if jnro and jyear else None,
                confidential=bool(p.get("salausperuste")),
                html=p.get("html") or "",
            )
        )
    return page


# -- item text ------------------------------------------------------------------------------

MARKER = re.compile(r"<p>\s*([A-ZÅÄÖ][A-Za-zÅÄÖåäö]{0,15})\s*§\s*(\d*)\s*</p>")
HEADING_SPAN = re.compile(r"<span class=\"ehdotuspaatos\"[^>]*>(.*?)</span>", re.DOTALL)
# Attachment rows inside the text ("Liite 1 Ohjausryhmän raportti"): the API lists them with links.
ATTACHMENT_ROW = re.compile(r"<p[^>]*class=\"[^\"]*liiteoheis[^\"]*\"[^>]*>.*?</p>", re.DOTALL)
# A paragraph that is only bold or underlined text is a subheading.
_ZW = "[\\s\u200b]*"
SUBHEAD = re.compile(
    rf"<p[^>]*>{_ZW}<(?:strong|span class=\"underline\")>((?:(?!</p>)[^<])*)</(?:strong|span)>{_ZW}</p>"
)
TAIL = re.compile(r"<div id=\"idTiedote\">.*", re.DOTALL)  # notice + distribution list (names)
TAGS = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return clean(TAGS.sub(" ", fragment).replace("​", ""))


def _kind_of(heading: str) -> SectionType:
    h = heading.lower()
    if h.startswith("päätös") and not h.startswith("päätösehdotus"):
        return SectionType.decision
    if "ehdotus" in h or h.startswith("esitys"):
        return SectionType.proposal
    return SectionType.other


def _subhead_kind(text: str) -> SectionType | None:
    t = text.lower()
    if "eriäv" in t:
        return SectionType.dissent
    if "pöytäkirjalausuma" in t:
        return SectionType.statement
    if "käsittely" in t or t.startswith("päätöksenteko"):
        return SectionType.deliberation
    return None


@dataclass
class Handling:
    body: str  # Kv, Kh …
    pykala: int | None
    html: str


def split_handlings(html: str) -> tuple[str, list[Handling]]:
    """(text before the first marker, handlings in order)."""
    html = TAIL.sub("", html)
    marks = list(MARKER.finditer(html))
    if not marks:
        return html, []
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(html)
        out.append(Handling(m.group(1), int(m.group(2)) if m.group(2) else None, html[m.end() : end]))
    return html[: marks[0].start()], out


def _sections(html: str, first: SectionType) -> list[Section]:
    """Sections of one handling. Text before the first heading is `first`."""
    html = ATTACHMENT_ROW.sub("", html)
    html = SUBHEAD.sub(lambda m: f"<h4>{m.group(1)}</h4>", html)
    html = HEADING_SPAN.sub(lambda m: f"<h3>{m.group(1)}</h3>", html)
    out: list[Section] = []
    kind, heading, lines = first, None, []

    def close() -> None:
        text = collapse_ws(strip_pii("\n\n".join(lines)))
        if text:
            out.append(Section(type=kind, heading=heading, text=text))

    for b in blocks(html):
        text = b.text.replace("​", "").strip()
        if b.kind == "table":
            lines.extend(" | ".join(c for c in r if c) for r in b.rows)
            continue
        if not text:
            continue
        if b.kind == "h3":
            close()
            kind, heading, lines = _kind_of(text), text, []
            continue
        if b.kind == "h4":
            sub = _subhead_kind(text)
            if sub is not None:
                close()
                kind, heading, lines = sub, text, []
                continue
        lines.append(text)
    close()
    return out


@dataclass
class ItemPage:
    sections: list[Section] = field(default_factory=list)
    own_lines: list[str] = field(default_factory=list)  # this meeting's proposal/decision/handling


def _paragraphs(sections) -> list[str]:
    return [p for s in sections for p in s.text.split("\n\n") if p.strip()]


def parse_item(html: str, body_abbr: str, pykala: int | None) -> ItemPage:
    lead, handlings = split_handlings(html)
    page = ItemPage()
    if not handlings:
        page.sections = _sections(lead, SectionType.background)
        page.own_lines = _paragraphs(page.sections)
        return page
    own = next(
        (
            i
            for i in range(len(handlings) - 1, -1, -1)
            if handlings[i].body == body_abbr and (pykala is None or handlings[i].pykala in (pykala, None))
        ),
        len(handlings) - 1,
    )
    if _text(lead):
        page.sections.extend(_sections(lead, SectionType.background))
    history: list[Section] = []
    for i, h in enumerate(handlings):
        secs = _sections(h.html, SectionType.background)
        if i == own:
            page.sections.extend(secs)
            page.own_lines = _paragraphs(s for s in secs if s.type != SectionType.background)
            continue
        # The presenter's background is written once, at the top of the first handling.
        if i == 0:
            page.sections.extend(s for s in secs if s.type == SectionType.background)
            secs = [s for s in secs if s.type != SectionType.background]
        label = f"{h.body} § {h.pykala}" if h.pykala else h.body
        for s in secs:
            history.append(
                Section(
                    type=SectionType.history, heading=f"{label}: {s.heading or ''}".rstrip(": "), text=s.text
                )
            )
    # History reads after the background, before this meeting's own handling.
    bg = [s for s in page.sections if s.type == SectionType.background]
    rest = [s for s in page.sections if s.type != SectionType.background]
    page.sections = bg + history + rest
    return page


# -- attachments ----------------------------------------------------------------------------


@dataclass
class AttachmentRow:
    title: str
    url: str
    kind: AttachmentKind


def parse_attachments(data: dict, body_abbr: str, pykala: int | None) -> list[Attachment]:
    """The meeting's own attachments (`{body}-{pykälä}`), else every group's (agenda items carry
    no pykälä yet). Confidential rows have no link and are left out."""
    if not isinstance(data, dict):
        return []
    key = f"{body_abbr}-{pykala}" if pykala is not None else None
    groups = [data[key]] if key and key in data else list(data.values())
    out: list[Attachment] = []
    seen: set[str] = set()
    for group in groups:
        for r in group or []:
            if str(r.get("suojattu")) == "1":
                continue
            kind = (
                AttachmentKind.supplementary
                if (r.get("tktviiteTyyppi") or "").startswith("oh")
                else AttachmentKind.attachment
            )
            for link in all_links(r.get("html") or "", BASE):
                if link.href in seen or "/doc/" not in link.href:
                    continue
                seen.add(link.href)
                title = link.text or clean(r.get("tktNimi") or "")
                out.append(Attachment(title=title, url=link.href, kind=kind))
    return out


# -- attendance -----------------------------------------------------------------------------


@dataclass
class Participant:
    name: str
    role: str


def parse_attendance(data: list) -> list[Participant]:
    """Name and role only; `nimike` (occupation) is personal data and is not kept."""
    out = []
    for r in data or []:
        name = clean(r.get("lasolNimi") or "")
        if name:
            out.append(Participant(name=name, role=clean(r.get("tehtava") or "")))
    return out


# -- votes ----------------------------------------------------------------------------------

VOTE_LIST_TITLE = re.compile(r"^\s*äänestyslist", re.IGNORECASE)
_COUNT_WORD = r"(?:valtuutettua|jäsentä|ääntä)"
# "56 valtuutettua kannatti asian käsittelyn jatkamista ja 11 valtuutettua kannatti Diopin …"
PROSE = re.compile(
    rf"(?P<a>\d+)\s+{_COUNT_WORD}\s+kannatti\s+.+?\s+ja\s+(?P<b>\d+)\s+{_COUNT_WORD}\s+kannatti\b"
    rf"(?:[^.]*?(?P<t>\d+)\s+{_COUNT_WORD}\s+äänesti\s+tyhjää)?",
    re.IGNORECASE | re.DOTALL,
)


def parse_prose(lines: list[str]) -> list[ProseVote]:
    text = re.sub(r"\s+", " ", " ".join(lines))
    out = []
    for m in PROSE.finditer(text):
        s = max(text.rfind(". ", 0, m.start()) + 2, 0)
        e = text.find(". ", m.end())
        sentence = text[s : (len(text) if e < 0 else e + 1)].strip()
        out.append(ProseVote(int(m.group("a")), int(m.group("b")), int(m.group("t") or 0), sentence))
    return out


PDF_ASIA = re.compile(r"^Asia\s*/\s*Ärende\s+(\d+)\b")
PDF_VOTE = re.compile(r"^Äänestys\s*/\s*Omröstning\s+(\d+)")
PDF_SIDE = re.compile(r"^(Jaa|Ei)\s*/\s*(?:Ja|Nej)\s+(.*\D.*)$")
PDF_COUNT = re.compile(r"^(Jaa|Ei|Tyhjää|Poissa)\s*/\s*(?:Ja|Nej|Blankt|Frånvarande)\s+(\d+)$")
# "Aalto-Setälä Matti KOK J Lindén Aki SDP J": name, party (capitals), J/E/T/P.
VOTER = re.compile(
    r"(?P<name>[A-ZÅÄÖÉ][^\s]*(?:\s+[^\s]+?)*?)\s+(?P<party>[A-ZÅÄÖ]{1,6})\s+(?P<c>[JETP])(?=\s|$)"
)
LETTER = {"J": Choice.jaa, "E": Choice.ei, "T": Choice.tyhja, "P": Choice.poissa}
COUNT_WORD = {"jaa": Choice.jaa, "ei": Choice.ei, "tyhjää": Choice.tyhja, "poissa": Choice.poissa}


def _side_label(raw: str) -> str:
    """ "Ehdotus / Förslag Kh" → "Ehdotus Kh"; "Muutos / Ändring Diop Paco (Ekman Johan)" →
    "Muutos Diop Paco" (the seconder in brackets is dropped)."""
    raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
    raw = re.sub(r"^(\S+)\s*/\s*\S+\s*", r"\1 ", raw)
    return re.sub(r"\s+", " ", raw).strip()


@dataclass
class TurkuPdfVote(PdfVote):
    agenda_no: str | None = None
    groups: dict[str, str] = field(default_factory=dict)  # voter name → party


def parse_vote_pdf_lines(lines: list[str]) -> list[TurkuPdfVote]:
    votes: list[TurkuPdfVote] = []
    asia: str | None = None
    cur: TurkuPdfVote | None = None
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line.startswith("Äänestyslista"):
            continue
        if m := PDF_ASIA.match(line):
            asia = m.group(1)
            continue
        if PDF_VOTE.match(line):
            cur = TurkuPdfVote(agenda_no=asia)
            votes.append(cur)
            continue
        if cur is None:
            continue
        if m := PDF_COUNT.match(line):
            cur.counts[COUNT_WORD[m.group(1).lower()]] = int(m.group(2))
            continue
        if m := PDF_SIDE.match(line):
            label = _side_label(m.group(2))
            if m.group(1) == "Jaa":
                cur.jaa_label = label
            else:
                cur.ei_label = label
            continue
        found = list(VOTER.finditer(line))
        if not found:
            cur.leftover.append(line)
            continue
        for v in found:
            name = v.group("name").strip()
            cur.ballots.append((name, LETTER[v.group("c")]))
            cur.groups[name] = v.group("party")
        rest = VOTER.sub("", line).strip()
        if rest:
            cur.leftover.append(rest)
    for v in votes:
        cast = sum(n for c, n in v.counts.items() if c != Choice.poissa)
        v.total = cast or None
    return votes


def parse_vote_pdf(data: bytes) -> list[TurkuPdfVote]:
    from ..pdf import pdf_pages

    return parse_vote_pdf_lines([ln for page in pdf_pages(data) for ln in page])
