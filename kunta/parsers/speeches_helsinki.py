"""Helsinki council speech transcripts ("keskustelupöytäkirja", PLAN.md §7.1 Speeches).

One PDF per council meeting, linked from the meeting page (`source_ids.transcript_pdf`). After the
repeated bilingual header and footer are dropped, the text is: a cover in Finnish and Swedish, a
table of contents ("Sisällysluettelo"), then the body. The contents list every item that had
speeches and every speaker heading in order, each line ending in dot leaders and a page number:

    256 § ............ 6
    Esityslistan asia nro 8 ............ 6
    Helsingin kaupungin ympäristöraportti 2025 ............ 6
    Apulaispormestari Johanna Laisaari ............ 6
    Valtuutettu Arja Karhuvaara (vastauspuheenvuoro) ............ 9

The body repeats those headings without leaders. Speeches are cut at the headings, matched in
contents order, so a sentence that happens to start with "Valtuutettu" never opens a speech.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Lang, PersonRef, Speech, SpeechKind
from ..text import collapse_ws, strip_pii

_LEADER = re.compile(r"\s*\.{3,}\s*\d+\s*$")
_PYKALA = re.compile(r"^(\d+)\s*§$")
_ASIA = re.compile(r"^Esityslistan\s+asia\s+(?:nro|n:o)\.?\s*(\d+)$", re.IGNORECASE)
_REPLY = re.compile(r"\s*\((vastauspuheenvuoro|replik)\)\s*$", re.IGNORECASE)
# Titles printed before the speaker's name ("Valtutettu" is a typo seen in a 2025 transcript).
_TITLES = re.compile(
    r"^(Valtuutettu|Valtutettu|Varavaltuutettu|Ledamoten|Ledamot|Ersättaren"
    r"|Apulaispormestari|Biträdande borgmästaren|Pormestari|Borgmästaren"
    r"|Puheenjohtaja|Ordföranden|Kaupunginjohtaja|Kansliapäällikkö"
    r"|Nuorisoneuvoston edustaja|Nuorisovaltuuston edustaja|Ungdomsrådets representant)\s+(.+)$"
)
_SWEDISH = re.compile(r"^(Ledamot|Ersättaren|Biträdande|Borgmästaren|Ordföranden|Ungdomsrådets)")


@dataclass
class Heading:
    text: str  # the heading as printed, whitespace collapsed
    title: str
    name: str
    kind: SpeechKind
    lang: Lang


@dataclass
class TocItem:
    pykala: int
    ordinal: int | None = None
    speakers: list[Heading] = field(default_factory=list)


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _key(line: str) -> str:
    # Headings are compared without spaces: "Saxberg(vastauspuheenvuoro)" and "262§" occur.
    return re.sub(r"\s+", "", line).lower()


def parse_heading(text: str) -> Heading | None:
    text = _norm(text)
    m = _REPLY.search(text)
    kind = SpeechKind.reply if m else SpeechKind.speech
    rest = text[: m.start()].strip() if m else text
    t = _TITLES.match(rest)
    if t:
        title, name = t.group(1), t.group(2).strip()
    elif rest.lower().startswith("esityslistan"):
        return None
    else:
        title, name = "", rest  # a few headings print the name alone
    if not name or len(name) > 80 or any(ch.isdigit() for ch in name):
        return None
    lang = Lang.sv if _SWEDISH.match(title) or (m and m.group(1).lower() == "replik") else Lang.fi
    return Heading(text, title, name, kind, lang)


def parse_toc(lines: list[str]) -> tuple[list[TocItem], int]:
    """The contents and the index of the first body line. Entries can wrap; an entry ends on the
    line carrying its page number."""
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip().lower() == "sisällysluettelo")
    except StopIteration:
        return [], 0
    entries: list[str] = []
    buf: list[str] = []
    i = start + 1
    while i < len(lines):
        ln = lines[i].strip()
        if _LEADER.search(ln):
            entries.append(_norm(" ".join([*buf, _LEADER.sub("", ln)])))
            buf = []
        elif entries and _key(ln) == _key(entries[0]):
            break  # the body starts by repeating the first entry
        elif ln:
            buf.append(ln)
        i += 1
    items: list[TocItem] = []
    expect_title = False
    for e in entries:
        if m := _PYKALA.match(e):
            items.append(TocItem(int(m.group(1))))
            expect_title = False
        elif items and (m := _ASIA.match(e)):
            items[-1].ordinal = int(m.group(1))
            expect_title = True
        elif items and expect_title:
            expect_title = False  # the item title; the body prints it too, wrapped differently
        elif items and (h := parse_heading(e)):
            items[-1].speakers.append(h)
    return items, i


@dataclass
class _Open:
    item: TocItem
    heading: Heading
    lines: list[str]


def _paragraphs(lines: list[str]) -> str:
    """Join wrapped lines; a short line ending a sentence closes a paragraph."""
    width = max((len(ln) for ln in lines), default=0)
    paras: list[str] = []
    cur = ""
    for ln in (ln.strip() for ln in lines):
        if not ln:
            continue
        cur = cur[:-1] + ln if cur.endswith("-") and ln[:1].islower() else f"{cur} {ln}".strip()
        if ln[-1:] in ".!?:" and len(ln) < 0.8 * width:
            paras.append(cur)
            cur = ""
    if cur:
        paras.append(cur)
    return "\n\n".join(paras)


def parse_transcript(
    lines: list[str],
    meeting_id: str,
    items_by_ordinal: dict[int, tuple[str, int | None]],
    source_url: str,
) -> tuple[list[Speech], int]:
    """Speeches of one meeting in order, and the number of speaker headings in the contents.

    `lines` are the PDF's lines with page headers and footers removed. `items_by_ordinal` maps the
    meeting's agenda ordinals to (item id, pykälä); a speech links to an item only when both match.
    """
    toc, body_start = parse_toc(lines)
    expected = [(item, h) for item in toc for h in item.speakers]
    out: list[Speech] = []
    nxt = 0  # next expected heading
    cur: _Open | None = None

    def close() -> None:
        if cur is None:
            return
        text = strip_pii(collapse_ws(_paragraphs(cur.lines)))
        if not text:
            return
        item_id = None
        if cur.item.ordinal is not None and cur.item.ordinal in items_by_ordinal:
            iid, pykala = items_by_ordinal[cur.item.ordinal]
            if pykala in (None, cur.item.pykala):
                item_id = iid
        h = cur.heading
        out.append(
            Speech(
                id=f"{meeting_id}/s{len(out) + 1}",
                meeting_id=meeting_id,
                item_id=item_id,
                ordinal=len(out) + 1,
                speaker_ref=PersonRef(raw=h.name),
                speaker_title=h.title,
                kind=h.kind,
                lang=h.lang,
                text=text,
                source_url=source_url,
            )
        )

    skipping_item_head = False
    for raw in lines[body_start:]:
        ln = _norm(raw)
        if not ln:
            continue
        k = _key(ln)
        # A heading may be missed (printed differently from the contents): look a few ahead.
        hit = next(
            (j for j in range(nxt, min(nxt + 3, len(expected))) if _key(expected[j][1].text) == k),
            None,
        )
        if hit is not None:
            close()
            item, h = expected[hit]
            cur = _Open(item, h, [])
            nxt = hit + 1
            skipping_item_head = False
            continue
        if (m := _PYKALA.match(ln)) and any(i.pykala == int(m.group(1)) for i in toc):
            close()
            cur = None
            skipping_item_head = True  # "Esityslistan asia nro N" and the title follow
            continue
        if skipping_item_head or cur is None:
            continue
        cur.lines.append(raw)
    close()
    return out, len(expected)
