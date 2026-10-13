"""Helsinki HTML votes and motions (PLAN.md §7.1).

Two sources on an item page, both for the current body only:

- text blocks in Käsittely, each headed "N äänestys" (or "N. äänestys"), with JAA-/EI-ehdotus
  labels, then "Jaa-äänet: N" and a comma-separated list of names ("Etunimi Sukunimi"), then
  Ei-äänet, Tyhjä, Poissa, then the result sentence;
- the "Äänestystulokset" accordion: per vote an "Äänestys K" heading, then per choice a
  "N Jaa" / "N Ei" / "N Tyhjä" / "N Poissa" heading and a table Jäsen | Valtuustoryhmä
  (names as "Sukunimi, Etunimi"), then a per-group summary table.

The printed vote numbers do not agree between the two ("3 äänestys" vs "Äänestys 1"), so text
blocks and tables are paired by order of appearance and confirmed by equal counts.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..htmlblocks import Block
from ..models import Ballot, Choice, Counts, Motion, MotionKind, Outcome, PersonRef, VoteEvent, VoteSource

VOTE_HEAD = re.compile(r"^(\d+)\.?\s+äänestys$", re.IGNORECASE)
TABLE_VOTE_HEAD = re.compile(r"^Äänestys\s+(\d+)$", re.IGNORECASE)
TABLE_CHOICE_HEAD = re.compile(r"^(\d+)\s+(Jaa|Ei|Tyhjä|Poissa)$", re.IGNORECASE)
COUNT_LINE = re.compile(r"^(Jaa-äänet|Ei-äänet|Tyhjä|Tyhjiä|Poissa)\s*:\s*(\d+)\s*(.*)$", re.IGNORECASE)
JAA_LABEL = re.compile(r"^JAA-ehdotus\s*:\s*(.*)$", re.IGNORECASE)
EI_LABEL = re.compile(r"^EI-ehdotus\s*:\s*(.*)$", re.IGNORECASE)
SECONDER = re.compile(r"^Kannattaja(?:t)?\s*:\s*(.*)$", re.IGNORECASE)
MOTION_HEAD = re.compile(
    r"^(Vastaehdotus|Palautusehdotus|Pöydällepanoehdotus|Toivomusponsi|Toivomusponsiehdotus|"
    r"Muutosehdotus|Hylkäysehdotus)(?:\s+\d+)?\s*:?\s*(.*)$",
    re.IGNORECASE,
)
_MOTION_KINDS = {
    "vastaehdotus": MotionKind.counter_proposal,
    "muutosehdotus": MotionKind.counter_proposal,
    "hylkäysehdotus": MotionKind.counter_proposal,
    "palautusehdotus": MotionKind.send_back,
    "pöydällepanoehdotus": MotionKind.table,
    "toivomusponsi": MotionKind.resolution,
    "toivomusponsiehdotus": MotionKind.resolution,
}
_CHOICE = {
    "jaa-äänet": Choice.jaa,
    "jaa": Choice.jaa,
    "ei-äänet": Choice.ei,
    "ei": Choice.ei,
    "tyhjä": Choice.tyhja,
    "tyhjiä": Choice.tyhja,
    "poissa": Choice.poissa,
}
TITLES = (
    "valtuutettu",
    "varavaltuutettu",
    "jäsen",
    "varajäsen",
    "puheenjohtaja",
    "varapuheenjohtaja",
    "ensimmäinen varapuheenjohtaja",
    "toinen varapuheenjohtaja",
    "apulaispormestari",
    "pormestari",
    "ledamoten",
    "ledamot",
)
_TITLE_RX = re.compile(r"^(?:" + "|".join(sorted(TITLES, key=len, reverse=True)) + r")\s+", re.IGNORECASE)
_PROPOSER_RX = re.compile(
    r"^([A-ZÅÄÖÜ][\w'’-]+(?:\s+(?:af|von|de|van)?\s*[A-ZÅÄÖÜ][\w'’-]+){1,3})\s+"
    r"(?:teki|ehdotti|esitti)",
)


def strip_title(name: str) -> str:
    return _TITLE_RX.sub("", name.strip()).strip()


def split_names(text: str) -> list[str]:
    return [n for n in (p.strip().rstrip(".") for p in text.split(",")) if n]


@dataclass
class TextVote:
    jaa_label: str = ""
    ei_label: str = ""
    counts: dict[Choice, int] = field(default_factory=dict)
    names: dict[Choice, list[str]] = field(default_factory=dict)
    result: list[str] = field(default_factory=list)


@dataclass
class TableVote:
    counts: dict[Choice, int] = field(default_factory=dict)
    rows: dict[Choice, list[tuple[str, str | None]]] = field(default_factory=dict)


def parse_text_votes(lines: list[str]) -> list[TextVote]:
    votes: list[TextVote] = []
    cur: TextVote | None = None
    expect_names: Choice | None = None
    for line in lines:
        if VOTE_HEAD.match(line):
            cur = TextVote()
            votes.append(cur)
            expect_names = None
            continue
        if cur is None:
            continue
        if m := JAA_LABEL.match(line):
            cur.jaa_label = m.group(1).strip()
        elif m := EI_LABEL.match(line):
            cur.ei_label = m.group(1).strip()
        elif m := COUNT_LINE.match(line):
            choice = _CHOICE[m.group(1).lower()]
            cur.counts[choice] = int(m.group(2))
            rest = m.group(3).strip()
            if rest:
                cur.names[choice] = split_names(rest)
                expect_names = None
            else:
                expect_names = choice if int(m.group(2)) > 0 else None
        elif expect_names is not None:
            cur.names[expect_names] = split_names(line)
            expect_names = None
        elif MOTION_HEAD.match(line) or SECONDER.match(line):
            cur = None  # a new motion block ends the vote
        elif cur.counts and len(cur.result) < 2:
            cur.result.append(line)
    return votes


def parse_table_votes(blocks: list[Block]) -> list[TableVote]:
    """Blocks of the Äänestystulokset accordion, in order."""
    votes: list[TableVote] = []
    cur: TableVote | None = None
    choice: Choice | None = None
    for b in blocks:
        text = b.text
        if b.kind != "table" and (TABLE_VOTE_HEAD.match(text)):
            cur = TableVote()
            votes.append(cur)
            choice = None
        elif b.kind != "table" and (m := TABLE_CHOICE_HEAD.match(text)):
            if cur is None:
                cur = TableVote()
                votes.append(cur)
            choice = _CHOICE[m.group(2).lower()]
            cur.counts[choice] = int(m.group(1))
        elif b.kind == "table" and cur is not None and b.rows:
            header = [h.lower() for h in b.rows[0]]
            if header and header[0] == "jäsen" and choice is not None:
                gi = header.index("valtuustoryhmä") if "valtuustoryhmä" in header else None
                rows = cur.rows.setdefault(choice, [])
                for r in b.rows[1:]:
                    if r and r[0]:
                        rows.append((r[0], r[gi] if gi is not None and gi < len(r) and r[gi] else None))
            choice = None  # summary tables and anything after belong to no choice
    return votes


def _counts(d: dict[Choice, int]) -> Counts:
    return Counts(**{c.value: d.get(c, 0) for c in Choice})


def _ballot_mismatch(counts: Counts, ballots: list[Ballot]) -> list[str]:
    got = Counter(b.choice for b in ballots)
    return [
        f"{c.value}: {got.get(c.value, 0)} names vs {getattr(counts, c.value)} printed"
        for c in Choice
        if got.get(c.value, 0) != getattr(counts, c.value) and (got.get(c.value, 0) or c != Choice.poissa)
    ]


def _key(name: str) -> str:
    return " ".join(sorted(re.findall(r"[\w-]+", name.lower())))


def _table_disagreement(ballots: list[Ballot], table: TableVote) -> str:
    """The city's own vote table and minutes text can disagree (seen on three council votes in
    2025–2026, each one member recorded with a different choice). The text is the minutes, so its
    ballots stand; the table still gives each member's group. The reason names who differs."""
    in_table = {_key(name): (c, name, group) for c in Choice for name, group in table.rows.get(c, [])}
    differs: list[str] = []
    for i, b in enumerate(ballots):
        hit = in_table.get(_key(b.person_ref.raw))
        if hit is None:
            continue
        choice, _, group = hit
        if group:
            ballots[i] = b.model_copy(update={"group_text": group})
        if choice != b.choice:
            differs.append(
                f"{b.person_ref.raw} ({b.choice.title()} in the text, {choice.value.title()} in the table)"
            )
    if differs:
        return (
            "the city's vote table and minutes text disagree: "
            + ", ".join(differs).replace("Tyhja", "Tyhjä")
            + "; counts and ballots follow the minutes text"
        )
    return "vote table counts differ from text counts; ballots taken from text"


def build_votes(text_votes: list[TextVote], table_votes: list[TableVote], source_url: str) -> list[VoteEvent]:
    events: list[VoteEvent] = []
    for i, tv in enumerate(text_votes, start=1):
        counts = _counts(tv.counts)
        table = table_votes[i - 1] if i - 1 < len(table_votes) else None
        reasons: list[str] = []
        ballots: list[Ballot]
        if table is not None and all(
            table.counts.get(c, 0) == tv.counts.get(c, 0) for c in (Choice.jaa, Choice.ei, Choice.tyhja)
        ):
            ballots = [
                Ballot(person_ref=PersonRef(raw=name), choice=c, group_text=group)
                for c in Choice
                for name, group in table.rows.get(c, [])
            ]
        else:
            ballots = [
                Ballot(person_ref=PersonRef(raw=strip_title(name)), choice=c)
                for c in Choice
                for name in tv.names.get(c, [])
            ]
            if table is not None:
                reasons.append(_table_disagreement(ballots, table))
        # Absent members are often only counted, not named; that alone is not a mismatch.
        mismatch = [
            m
            for m in _ballot_mismatch(counts, ballots)
            if not (m.startswith("poissa") and not any(b.choice == "poissa" for b in ballots))
        ]
        reasons.extend(mismatch)
        if not tv.jaa_label or not tv.ei_label:
            reasons.append("missing JAA/EI proposal label")
        events.append(
            VoteEvent(
                ordinal=i,
                jaa_label=tv.jaa_label,
                ei_label=tv.ei_label,
                counts=counts,
                ballots=ballots,
                result_text=" ".join(tv.result) or None,
                source=VoteSource.html,
                source_url=source_url,
                needs_review=bool(reasons),
                review_reason="; ".join(reasons) or None,
            )
        )
    return events


def parse_motions(lines: list[str]) -> list[Motion]:
    motions: list[Motion] = []
    cur: dict | None = None

    def close() -> None:
        nonlocal cur
        if cur is None:
            return
        text_lines = cur["lines"]
        proposer = ""
        if text_lines and len(text_lines[0].split()) <= 5 and not text_lines[0].endswith((".", ":")):
            proposer = strip_title(text_lines.pop(0))
        elif text_lines and (m := _PROPOSER_RX.match(strip_title(text_lines[0]))):
            proposer = m.group(1)
        motions.append(
            Motion(
                kind=cur["kind"],
                proposer_ref=PersonRef(raw=proposer),
                seconder_refs=[PersonRef(raw=s) for s in cur["seconders"]],
                text="\n\n".join(text_lines),
                outcome=None,
            )
        )
        cur = None

    for line in lines:
        if m := MOTION_HEAD.match(line):
            close()
            cur = {"kind": _MOTION_KINDS[m.group(1).lower()], "lines": [], "seconders": []}
            if rest := m.group(2).strip():
                cur["lines"].append(rest)
        elif VOTE_HEAD.match(line):
            close()
        elif cur is not None and (m := SECONDER.match(line)):
            cur["seconders"].extend(strip_title(n) for n in re.split(r",| ja ", m.group(1)) if n.strip())
        elif cur is not None and not cur["seconders"]:
            cur["lines"].append(line)
        elif cur is not None:
            close()
    close()
    return motions


def resolve_outcomes(motions: list[Motion], votes: list[VoteEvent]) -> None:
    """Set a motion's outcome when a vote's JAA or EI label names its proposer.

    Labels inflect the surname ("Otso Kivekkään ehdottama"), so match the first name followed by
    the first four letters of the surname. Ties and unmatched motions stay unknown (None).
    """
    for m in motions:
        parts = m.proposer_ref.raw.split()
        if len(parts) < 2:
            continue
        needle = f"{parts[0]} {parts[-1][:4]}"
        for v in votes:
            side = "jaa" if needle in v.jaa_label else "ei" if needle in v.ei_label else None
            if side is None:
                continue
            if v.counts.jaa != v.counts.ei:
                winner = "jaa" if v.counts.jaa > v.counts.ei else "ei"
                m.outcome = Outcome.adopted if winner == side else Outcome.rejected
            break
