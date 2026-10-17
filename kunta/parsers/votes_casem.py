"""Tampere votes and motions (PLAN.md §7.3, §16 S2).

Ballots are on the item page itself, one block per vote in `div.votingResults`:

    Juho Hirvelän muutosehdotus 1:            ← header: whose motion, kind, number
    Kaupunginhallituksen ehdotus JAA          ← what Jaa means
    Muutosehdotuksen hyväksyminen EI          ← what Ei means
      Kyllä 61 kpl 92%   Suomi Iia-Elisabeth, Lyly Lauri, …     ("Kyllä" is the Jaa side)
      Ei 5 kpl 8%        Vigelius Joakim, Hirvelä Juho, …
      (Tyhjä / Poissa rows when there are any)

Blocks are in voting order, which is not the order the motions are written in Kokouskäsittely.
Each block is checked against itself (names per row = the row's count) and against the minutes
text: "Äänestyksen tulos: Muutosehdotus hylättiin äänin 61-5[, tyhjiä n][, poissa n]." The pair is
the winner's count first, so it is compared without order. Members absent for one vote (for
example after declaring a conflict of interest) are only in the text's "poissa n", which stays in
`result_text`; counts follow the named ballots.

Motions are written as "Juho Hirvelä oli tehnyt seuraavat muutosehdotukset …:" followed by
"Muutosehdotus 1: …" blocks, or "Matti Helimo oli tehnyt seuraavan muutosehdotuksen:" and the
text; seconders as "Marika Puolimatka kannatti Juho Hirvelän muutosehdotuksia". A motion renewed
by someone else ("…, jotka Lasse Heikkilä uudisti") is recorded under the person who renewed it,
as the vote headers do.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..htmlblocks import clean
from ..models import Ballot, Choice, Counts, Motion, MotionKind, Outcome, PersonRef, VoteEvent, VoteSource

NAME = r"[A-ZÅÄÖ][\w'’-]+(?:\s+(?:af|von|de|van)\s+[A-ZÅÄÖ]?[\w'’-]+|\s+[A-ZÅÄÖ][\w'’-]+)+"
KINDS = {
    "muutosehdotu": MotionKind.counter_proposal,
    "vastaehdotu": MotionKind.counter_proposal,
    "palautusehdotu": MotionKind.send_back,
    "pöydällepanoehdotu": MotionKind.table,
    "ponsi": MotionKind.resolution,
    "ponne": MotionKind.resolution,
    "toivomusponsi": MotionKind.resolution,
    "hylkäysehdotu": MotionKind.other,
}
_KIND_WORD = r"(?:muutos|vasta|palautus|pöydällepano|hylkäys)ehdotu\w*|(?:toivomus)?pon(?:si|ne\w*)"
INTRO = re.compile(rf"^(?P<prop>{NAME})\s+oli\s+tehnyt\s+(?P<rest>.*)$")
RENEWED = re.compile(rf"jotka\s+(?P<who>{NAME})\s+uudisti")
SECONDED = re.compile(
    rf"^(?P<names>{NAME}(?:\s*(?:,|\s+ja\s+)\s*{NAME})*)\s+kannatti(?:vat)?\s+(?P<rest>.*)$"
)
NUMBERED = re.compile(
    r"^(?P<label>(?:Muutos|Vasta|Palautus|Pöydällepano)ehdotus|(?:Toivomus)?[Pp]onsi)\s+(?P<num>\d+)\b\s*:?\s*(?P<rest>.*)$"
)
REJECTION = re.compile(r"^Hylkäysehdotus\s*:?\s*$")
STOP = re.compile(
    r"^(Puheenjohtajan äänestysesitys|Äänestyksen tulos|Asian käsittelyn kuluessa|Keskustelun kuluessa)"
)
RESULT = re.compile(
    r"(?:Äänestyksen|Äänestysesityksen) tulos:\s*(?P<what>[\w-]+(?:\s+[\w-]+){0,3}?)\s+"
    r"(?P<verb>hyväksyttiin|hylättiin|voitti)\s+äänin\s+(?P<a>\d+)\s*[-–]\s*(?P<b>\d+)(?:,\s*tyhj(?:ä|iä|ää)\s+(?P<t>\d+))?"
    r"(?:,\s*poissa\s+(?P<p>\d+))?",
    re.IGNORECASE,
)
UNANIMOUS = re.compile(
    rf"(?P<gen>{NAME})\s+(?P<what>\w*ehdotus|\w*pon(?:si|net))\s+hyväksyttiin\s+yksimielisesti"
)
LAPSED = re.compile(rf"(?P<gen>{NAME})\s+(?P<what>\w*ehdotus|\w*pon(?:si|net))\s+raukesi")
HEADER = re.compile(rf"^(?P<gen>{NAME})\s+(?P<what>\w+?)(?:\s+(?P<num>\d+))?\s*:?$")
ROW = re.compile(r"^(?P<label>Kyllä|Jaa|Ei|Tyhjä|Tyhjiä|Poissa)\s+(?P<n>\d+)\s*kpl", re.IGNORECASE)
CHOICES = {
    "kyllä": Choice.jaa,
    "jaa": Choice.jaa,
    "ei": Choice.ei,
    "tyhjä": Choice.tyhja,
    "tyhjiä": Choice.tyhja,
    "poissa": Choice.poissa,
}


def _kind(word: str) -> MotionKind:
    w = word.lower()
    for stem, kind in KINDS.items():
        if w.startswith(stem) or stem in w:
            return kind
    return MotionKind.other


def _stem(word: str) -> str:
    """ "muutosehdotus" / "muutosehdotuksen" / "Muutosehdotus" → "muutosehdotu"."""
    w = word.lower()
    for stem in KINDS:
        if stem in w:
            return stem
    return w


def is_genitive_of(gen: str, name: str) -> bool:
    """Whether "Juho Hirvelän" is the genitive of "Juho Hirvelä" (first names stay as printed)."""
    g, n = gen.split(), name.split()
    if len(g) != len(n) or g[:-1] != n[:-1]:
        return False
    a, b = g[-1].lower(), n[-1].lower()
    if a in (b + "n", b + "in", b + "en") or (b.endswith("nen") and a == b[:-3] + "sen"):
        return True
    return len(b) >= 4 and a.startswith(b[:-1]) and len(a) <= len(b) + 2


# -- motions ------------------------------------------------------------------------------


@dataclass
class ProseResult:
    line: str
    pair: tuple[int, int]  # sorted (smaller, larger) of the two counts
    tyhja: int
    poissa: int


@dataclass
class _Draft:
    motion: Motion
    number: int | None
    lines: list[str] = field(default_factory=list)
    result: ProseResult | None = None
    open: bool = True


def _names(text: str) -> list[str]:
    return [n.strip() for n in re.split(r",|\s+ja\s+", text) if n.strip()]


def parse_motions(lines: list[str]) -> tuple[list[Motion], list[_Draft]]:
    """Motions in a Kokouskäsittely text, with the prose result of each vote attached to the motion
    it decided. Returns the motions and their drafts (for pairing with the vote blocks)."""
    drafts: list[_Draft] = []
    proposer: str | None = None
    proposer_kind: MotionKind = MotionKind.counter_proposal
    pending_single = False  # "seuraavan muutosehdotuksen:" → the next lines are its text
    current: _Draft | None = None
    seconders: dict[str | None, list[str]] = {}

    def start(kind: MotionKind, number: int | None, first: str | None) -> _Draft:
        d = _Draft(Motion(kind=kind, proposer_ref=PersonRef(raw=proposer or ""), text=""), number)
        if first:
            d.lines.append(first)
        drafts.append(d)
        return d

    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if m := INTRO.match(line):
            renewed = RENEWED.search(line)
            proposer = renewed.group("who") if renewed else m.group("prop")
            kinds = re.findall(_KIND_WORD, m.group("rest"), re.IGNORECASE)
            proposer_kind = _kind(kinds[0]) if kinds else MotionKind.other
            single = bool(re.search(r"\bseuraavan\b", m.group("rest"))) and line.endswith(":")
            current = start(proposer_kind, None, None) if single else None
            pending_single = single
            continue
        if m := SECONDED.match(line):
            # Seconders of the motions in hand, including numbered ones that follow. A renewer
            # seconding the motions they renewed is the proposer, not a seconder.
            seconders[proposer] = [n for n in _names(m.group("names")) if n != proposer]
            pending_single = False
            _outcomes(line, drafts)
            continue
        if m := NUMBERED.match(line):
            current = start(_kind(m.group("label")), int(m.group("num")), line)
            pending_single = False
            continue
        if REJECTION.match(line):
            current = start(MotionKind.other, None, line)
            continue
        if r := RESULT.search(line):
            if current is not None:
                current.result = _result(line, r)
                what = r.group("what").split()[-1].lower()
                # "voitti" settles a preliminary vote between two motions, not the motion's fate.
                if r.group("verb") != "voitti" and what.startswith(
                    ("muutos", "vasta", "hylkäys", "palautus", "pöydällepano", "pon")
                ):
                    current.motion.outcome = (
                        Outcome.adopted if r.group("verb") == "hyväksyttiin" else Outcome.rejected
                    )
                current.open = False
            continue
        if STOP.match(line):
            if current is not None:
                current.open = False
            continue
        if _outcomes(line, drafts):
            continue
        if (
            current is not None
            and current.open
            and (pending_single or current.number is not None or current.lines)
        ):
            current.lines.append(line)
    for d in drafts:
        d.motion.seconder_refs = [PersonRef(raw=n) for n in seconders.get(d.motion.proposer_ref.raw, [])]
        d.motion.text = "\n\n".join(d.lines) or (d.motion.kind == MotionKind.other and "Hylkäysehdotus") or ""
    kept = [d for d in drafts if d.motion.text]
    return [d.motion for d in kept], kept


def _outcomes(line: str, drafts: list[_Draft]) -> bool:
    """ "Matti Helimon muutosehdotus hyväksyttiin yksimielisesti." → adopted; "… raukesi" (no
    seconder) leaves the outcome open."""
    found = False
    for m in UNANIMOUS.finditer(line):
        kind = _kind(m.group("what"))
        open_ = [
            d for d in drafts
            if is_genitive_of(m.group("gen"), d.motion.proposer_ref.raw)
            and d.motion.kind == kind and d.motion.outcome is None
        ]  # fmt: skip
        if len(open_) == 1:
            open_[0].motion.outcome = Outcome.adopted
            found = True
    return found or bool(LAPSED.search(line))


# -- votes --------------------------------------------------------------------------------


@dataclass
class VoteBlock:
    header: str
    gen: str | None
    what: str | None
    number: int | None
    jaa_label: str
    ei_label: str
    counts: dict[Choice, int]
    ballots: list[tuple[str, Choice]]


def parse_vote_blocks(html: str) -> list[VoteBlock]:
    tree = HTMLParser(html)
    out: list[VoteBlock] = []
    for head in tree.css("div.votingResults-header"):
        parts = [clean(p) for p in head.text(deep=True, separator="\n").split("\n") if clean(p)]
        title = parts[0] if parts else ""
        jaa_label = ei_label = ""
        for p in parts[1:]:
            if p.upper().endswith(" JAA"):
                jaa_label = p[:-4].strip()
            elif p.upper().endswith(" EI"):
                ei_label = p[:-3].strip()
        body = head.next
        while body is not None and body.tag != "div":
            body = body.next
        counts: dict[Choice, int] = {}
        ballots: list[tuple[str, Choice]] = []
        for li in body.css("li") if body is not None else []:
            label = clean(li.css_first("span").text()) if li.css_first("span") else ""
            m = ROW.match(label)
            if not m:
                continue
            choice = CHOICES[m.group("label").lower()]
            counts[choice] = counts.get(choice, 0) + int(m.group("n"))
            names = clean(li.css_first("p").text()) if li.css_first("p") else ""
            ballots.extend((n.strip(), choice) for n in names.split(",") if n.strip())
        h = HEADER.match(title.rstrip(":").strip() + ":") if title else None
        out.append(
            VoteBlock(
                header=title.rstrip(":").strip(),
                gen=h.group("gen") if h else None,
                what=h.group("what") if h else None,
                number=int(h.group("num")) if h and h.group("num") else None,
                jaa_label=jaa_label,
                ei_label=ei_label,
                counts=counts,
                ballots=ballots,
            )
        )
    return out


def _result(line: str, r: re.Match) -> ProseResult:
    return ProseResult(
        line[r.start() :].strip(),
        tuple(sorted((int(r.group("a")), int(r.group("b"))))),
        int(r.group("t") or 0),
        int(r.group("p") or 0),
    )


def result_of(vote: VoteEvent) -> ProseResult:
    """A vote read from the minutes text, as a result sentence a vote block can be checked against."""
    c = vote.counts
    return ProseResult(vote.result_text or "", tuple(sorted((c.jaa, c.ei))), c.tyhja, c.poissa)


def parse_results(lines: list[str]) -> list[ProseResult]:
    """Every "Äänestyksen tulos: … äänin a-b" sentence, in text order."""
    found = []
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        found.extend(_result(line, r) for r in RESULT.finditer(line))
    return found


LABEL_MOTION = re.compile(rf"(?P<gen>{NAME})\s+(?P<what>{_KIND_WORD})", re.IGNORECASE)


def _match(block: VoteBlock, drafts: list[_Draft]) -> _Draft | None:
    """The motion a vote block decided: same proposer, kind and number. Board votes are headed by
    the two sides instead ("Esittelijän päätösehdotus JAA, Olga Haapa-ahon muutosehdotus EI"),
    so failing that, the one motion named in a side label, matched on the surname."""
    if block.gen is not None and block.what is not None:
        kind = _kind(block.what)
        cands = [
            d
            for d in drafts
            if is_genitive_of(block.gen, d.motion.proposer_ref.raw)
            and d.motion.kind == kind
            and d.number == block.number
        ]
        if len(cands) == 1:
            return cands[0]
    for label in (block.ei_label, block.jaa_label, block.header):
        for m in LABEL_MOTION.finditer(label or ""):
            kind, surname = _kind(m.group("what")), m.group("gen").split()[-1]
            cands = [
                d
                for d in drafts
                if d.motion.kind == kind
                and d.motion.proposer_ref.raw
                and is_genitive_of(surname, d.motion.proposer_ref.raw.split()[-1])
            ]
            if len(cands) == 1:
                return cands[0]
    return None


def build_votes(
    html: str, drafts: list[_Draft], item_url: str, results: list[ProseResult] | None = None
) -> list[VoteEvent]:
    """Vote events from the item page's blocks. Each block takes the prose result of the motion it
    decided; a block whose motion has none takes the first unused result sentence with the same
    pair of counts (`results`, from `parse_results`)."""
    blocks = parse_vote_blocks(html)
    matched = [_match(b, drafts) for b in blocks]
    spare = list(results or [])
    for d in matched:
        if d is not None and d.result in spare:
            spare.remove(d.result)
    events: list[VoteEvent] = []
    for i, (block, draft) in enumerate(zip(blocks, matched, strict=True), start=1):
        problems: list[str] = []
        per_choice = Counter(c for _, c in block.ballots)
        for choice, n in sorted(block.counts.items()):
            if per_choice.get(choice, 0) != n:
                problems.append(f"{choice.value}: {per_choice.get(choice, 0)} names for {n} votes")
        jaa, ei = block.counts.get(Choice.jaa, 0), block.counts.get(Choice.ei, 0)
        tyhja, poissa = block.counts.get(Choice.tyhja, 0), block.counts.get(Choice.poissa, 0)
        result = draft.result if draft is not None else None
        if result is None:
            same = [r for r in spare if r.pair == tuple(sorted((jaa, ei)))]
            if same:
                result = same[0]
                spare.remove(result)
        if result is None:
            problems.append("no matching result sentence in the minutes text")
        else:
            if tuple(sorted((jaa, ei))) != result.pair:
                problems.append(
                    f"minutes text says {result.pair[1]}–{result.pair[0]}, the vote list {jaa}–{ei}"
                )
            if result.tyhja and result.tyhja != tyhja:
                problems.append(f"minutes text says {result.tyhja} blank, the vote list {tyhja}")
        if draft is not None and draft.motion.outcome is None and jaa != ei:
            # Jaa is the base proposal in every Tampere vote seen; Ei carries the motion.
            draft.motion.outcome = Outcome.adopted if ei > jaa else Outcome.rejected
        events.append(
            VoteEvent(
                ordinal=i,
                jaa_label=block.jaa_label or "Jaa",
                ei_label=block.ei_label or "Ei",
                counts=Counts(jaa=jaa, ei=ei, tyhja=tyhja, poissa=poissa),
                ballots=[Ballot(person_ref=PersonRef(raw=n), choice=c) for n, c in block.ballots],
                result_text=f"{block.header}: {result.line}" if result else block.header,
                source=VoteSource.html,
                source_url=item_url,
                needs_review=bool(problems),
                review_reason="; ".join(problems) or None,
            )
        )
    return events
