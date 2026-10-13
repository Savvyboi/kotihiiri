"""Espoo votes: Käsittely prose + "Cloudmeeting Äänestystulosraportti" PDFs (PLAN.md §7.2).

The item's Käsittely states each result in prose ("Äänestyksessä valtuusto 30 äänellä 41 ääntä
vastaan, 4 äänestäessä tyhjää hylkäsi Nevanlinnan ehdotuksen. Äänestyslista on pöytäkirjan
liitteenä.") and the per-member list is an attachment titled "Äänestyslista § {pykälä}" (one vote)
or "Äänestyslistat § {pykälä}" (several). Two PDF layouts, both handled:

    Cloudmeeting Äänestystulosraportti            Cloudmeeting Äänestystulosraportti
    21.09.2026                                    08.12.2025
    Äänestystulosraportti                         Äänestystulosraportti
    Toimielin Valtuusto - Fullmäktige             Toimielin Valtuusto - Fullmäktige
    Kokous Valtuusto 21.09.2026                   Kokous Valtuusto 08.12.2025
    § 132 Valtuustoaloite … (may wrap)            § 167 Vuoden 2026 talousarvion … (may wrap)
    Nevanlinna Jaa / vastaan Ei / Tyhjä           1. Äänestys: Jaa: Immonen / Ei: vastaan / Tyhjä
    Annettuja ääniä yhteensä 75                   Annettuja ääniä yhteensä 75
    Äänet vaihtoehdoittain                        Äänet vaihtoehdoittain
    Ei 41 / Jaa 30 / Tyhjä 4 (one per line)       Jaa 38 / Ei 36 / Tyhjä 1
    Äänet äänestäjittäin                          Äänet äänestäjittäin
    Virtanen Matti Ei                             Virtanen Matti Ei
    …                                             …
                                                  2. Äänestys: Jaa: Hopsu 3.2 / Ei: vastaan / Tyhjä
                                                  …

Voter lines are "{Sukunimi} {Etunimi(s)} {Jaa|Ei|Tyhjä}": the last token is the choice. A deputy
can be printed with the member they replace on a second line ("Malkamäki Marianna",
"(Limnell Jarno)", "Ei"), so a line without a choice is carried over to the next. "Ei äänestänyt"
maps to poissa. No party/group column.

Votes are paired with the prose sentences by order and checked: ballots per choice == the PDF's
totals == the prose counts; otherwise `needs_review` with the reason.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..models import Ballot, Choice, Counts, Motion, MotionKind, Outcome, PersonRef, VoteEvent, VoteSource

# -- prose --------------------------------------------------------------------------------

# Number words in the cases the minutes use: "yhdellä äänellä", "yhtä ääntä vastaan",
# "yhden äänestäessä tyhjää".
_WORDS = [
    ("yksi", "yhdellä", "yhtä", "yhden"),
    ("kaksi", "kahdella", "kahta", "kahden"),
    ("kolme", "kolmella", "kolmea", "kolmen"),
    ("neljä", "neljällä", "neljää", "neljän"),
    ("viisi", "viidellä", "viittä", "viiden"),
    ("kuusi", "kuudella", "kuutta", "kuuden"),
    ("seitsemän", "seitsemällä", "seitsemää", "seitsemän"),
    ("kahdeksan", "kahdeksalla", "kahdeksaa", "kahdeksan"),
    ("yhdeksän", "yhdeksällä", "yhdeksää", "yhdeksän"),
    ("kymmenen", "kymmenellä", "kymmentä", "kymmenen"),
    ("yksitoista", "yhdellätoista", "yhtätoista", "yhdentoista"),
    ("kaksitoista", "kahdellatoista", "kahtatoista", "kahdentoista"),
    ("kolmetoista", "kolmellatoista", "kolmeatoista", "kolmentoista"),
]
NUMBER_WORDS = {w: n for n, forms in enumerate(_WORDS, start=1) for w in forms} | {"nolla": 0}
_NUM = r"(\d+|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + ")"
PROSE = re.compile(
    _NUM + r"\s+äänellä\s+" + _NUM + r"\s+ääntä\s+vastaan"
    r"(?:\s*,?\s*(?:ja\s+)?" + _NUM + r"\s+(?:jäsenen\s+|valtuutetun\s+)?äänestäessä\s+tyhjää)?",
    re.IGNORECASE,
)
VOTE_LIST_MENTION = re.compile(r"äänestyslista", re.IGNORECASE)


def _n(word: str) -> int:
    return int(word) if word.isdigit() else NUMBER_WORDS[word.lower()]


@dataclass
class ProseVote:
    a: int  # "N äänellä": votes for the proposal put to the vote as Jaa
    b: int  # "M ääntä vastaan"
    tyhja: int
    sentence: str


def _sentence_at(text: str, start: int, end: int) -> str:
    s = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    e = text.find(". ", end)
    e = len(text) if e < 0 else e + 1
    return text[s + 1 : e].strip()


def parse_prose(lines: list[str]) -> list[ProseVote]:
    text = re.sub(r"[ \t]+", " ", "\n".join(lines))
    return [
        ProseVote(
            _n(m.group(1)),
            _n(m.group(2)),
            _n(m.group(3)) if m.group(3) else 0,
            _sentence_at(text, m.start(), m.end()),
        )  # fmt: skip
        for m in PROSE.finditer(text)
    ]


def mentions_vote_list(lines: list[str]) -> bool:
    return any(VOTE_LIST_MENTION.search(ln) for ln in lines)


# -- PDF ----------------------------------------------------------------------------------

CHOICE_WORD = {"jaa": Choice.jaa, "ei": Choice.ei, "tyhjä": Choice.tyhja, "tyhja": Choice.tyhja}
TOTAL = re.compile(r"^Annettuja ääniä yhteensä\s+(\d+)$", re.IGNORECASE)
BY_OPTION = re.compile(r"^Äänet vaihtoehdoittain$", re.IGNORECASE)
BY_VOTER = re.compile(r"^Äänet äänestäjittäin$", re.IGNORECASE)
OPTION_LINE = re.compile(r"^(Jaa|Ei|Tyhjä|Ei äänestänyt|Poissa)\s+(\d+)$", re.IGNORECASE)
VOTE_START = re.compile(r"^(\d+)\.?\s*Äänestys\b\s*:?\s*(.*)$", re.IGNORECASE)
PYKALA = re.compile(r"^§\s*(\d+)\b")
HEADER = re.compile(
    r"^(Cloudmeeting\b|Äänestystulosraportti$|Toimielin\s|Kokous\s|\d{1,2}\.\d{1,2}\.\d{4}$|"
    r"Sivu\s+\d+|\d+\s*/\s*\d+$)",
    re.IGNORECASE,
)
VOTER = re.compile(r"^(.*?)\s*\(?\b(Jaa|Ei|Tyhjä|Ei äänestänyt|Poissa)\)?$")
PAREN = re.compile(r"\s*\([^)]*\)")


@dataclass
class PdfVote:
    pykala: int | None = None
    jaa_label: str = ""
    ei_label: str = ""
    total: int | None = None
    counts: dict[Choice, int] = field(default_factory=dict)
    ballots: list[tuple[str, Choice]] = field(default_factory=list)
    leftover: list[str] = field(default_factory=list)  # name fragments without a choice


def parse_legend(line: str) -> tuple[str, str]:
    """ "Nevanlinna Jaa / vastaan Ei / Tyhjä", "Jaa: Immonen / Ei: vastaan / Tyhjä",
    "Jaa Hopsu 3.3. / Ei: vastaan / Tyhjä", "Jaa / pohjaehdotus / Ei / 6.2" → (jaa, ei) labels."""
    parts = [p.strip() for p in line.split("/")]
    labels: dict[Choice, str] = {}
    pending: Choice | None = None
    for p in parts:
        m = re.match(r"^(Jaa|Ei|Tyhjä)\b\s*:?\s*(.*)$", p, re.IGNORECASE) or None
        tail = re.match(r"^(.*?)\s*\b(Jaa|Ei|Tyhjä)$", p, re.IGNORECASE)
        if m:
            choice, label = CHOICE_WORD[m.group(1).lower()], m.group(2).strip()
        elif tail:
            choice, label = CHOICE_WORD[tail.group(2).lower()], tail.group(1).strip()
        elif pending is not None:
            labels.setdefault(pending, p)
            pending = None
            continue
        else:
            continue
        if label:
            labels.setdefault(choice, label)
            pending = None
        else:
            pending = choice
    return labels.get(Choice.jaa, ""), labels.get(Choice.ei, "")


def _voter_name(fragments: list[str]) -> str:
    return re.sub(r"\s+", " ", PAREN.sub("", " ".join(fragments))).strip()


def parse_vote_pdf_lines(lines: list[str]) -> list[PdfVote]:
    votes: list[PdfVote] = []
    cur: PdfVote | None = None
    state = "header"  # header → options → voters
    pykala: int | None = None
    legend = ""
    buf: list[str] = []
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if m := TOTAL.match(line):
            if cur is not None and buf:
                cur.leftover.extend(buf)
            buf = []
            cur = PdfVote(pykala=pykala, total=int(m.group(1)))
            cur.jaa_label, cur.ei_label = parse_legend(legend)
            votes.append(cur)
            state, legend = "options", ""
            continue
        if BY_OPTION.match(line):
            state = "options"
            continue
        if BY_VOTER.match(line):
            state = "voters"
            continue
        if m := VOTE_START.match(line):
            legend, state = m.group(2), "header"
            if cur is not None and buf:
                cur.leftover.extend(buf)
            buf = []
            continue
        if m := PYKALA.match(line):
            pykala, state = int(m.group(1)), "header"
            if cur is not None and buf:
                cur.leftover.extend(buf)
            buf = []
            continue
        if HEADER.match(line):
            if state == "voters" and cur is not None and buf:
                cur.leftover.extend(buf)
                buf = []
            if line.lower().startswith(("cloudmeeting", "toimielin")):
                state = "header"
            continue
        if state == "header":
            if "/" in line and re.search(r"\b(Jaa|Ei)\b", line):
                legend = line
            continue
        if state == "options" and cur is not None:
            if m := OPTION_LINE.match(line):
                word = m.group(1).lower()
                choice = Choice.poissa if word in ("ei äänestänyt", "poissa") else CHOICE_WORD[word]
                cur.counts[choice] = cur.counts.get(choice, 0) + int(m.group(2))
            continue
        if state == "voters" and cur is not None:
            m = VOTER.match(line)
            if m is None:
                buf.append(line)
                continue
            word = m.group(2).lower()
            choice = Choice.poissa if word in ("ei äänestänyt", "poissa") else CHOICE_WORD[word]
            name = _voter_name([*buf, m.group(1)])
            buf = []
            if name:
                cur.ballots.append((name, choice))
            else:
                cur.leftover.append(line)
    if cur is not None and buf:
        cur.leftover.extend(buf)
    return votes


def parse_vote_pdf(data: bytes) -> list[PdfVote]:
    """No header/footer stripping: voter lines legitimately repeat across the votes of one PDF."""
    from ..pdf import pdf_pages

    return parse_vote_pdf_lines([ln for page in pdf_pages(data) for ln in page])


# -- pairing ------------------------------------------------------------------------------


def _counts(d: dict[Choice, int]) -> Counts:
    return Counts(**{c.value: d.get(c, 0) for c in Choice})


def build_votes(
    prose: list[ProseVote],
    pdf_votes: list[PdfVote],
    *,
    item_url: str,
    pdf_url: str | None,
    pdf_problem: str | None = None,
) -> list[VoteEvent]:
    events: list[VoteEvent] = []
    for i in range(max(len(prose), len(pdf_votes))):
        pv = prose[i] if i < len(prose) else None
        dv = pdf_votes[i] if i < len(pdf_votes) else None
        reasons: list[str] = []
        if dv is None:
            assert pv is not None
            reasons.append(
                pdf_problem or "no vote list in the PDF for this vote; counts from the minutes text"
            )
            events.append(
                VoteEvent(
                    ordinal=i + 1,
                    jaa_label="",
                    ei_label="",
                    counts=Counts(jaa=pv.a, ei=pv.b, tyhja=pv.tyhja),
                    result_text=pv.sentence,
                    source=VoteSource.html,
                    source_url=item_url,
                    needs_review=True,
                    review_reason="; ".join(reasons),
                )
            )
            continue
        ballots = [Ballot(person_ref=PersonRef(raw=name), choice=c) for name, c in dv.ballots]
        counts = _counts(dv.counts)
        got = Counter(c for _, c in dv.ballots)
        for c in Choice:
            printed = getattr(counts, c.value)
            if got.get(c, 0) != printed and (printed or c != Choice.poissa or got.get(c, 0)):
                reasons.append(f"{c.value}: {got.get(c, 0)} names vs {printed} in the PDF totals")
        cast = sum(dv.counts.get(c, 0) for c in Choice if c != Choice.poissa)
        if dv.total is not None and dv.total not in (cast, cast + dv.counts.get(Choice.poissa, 0)):
            reasons.append(f"PDF total {dv.total} differs from the sum of its options")
        if dv.leftover:
            reasons.append(f"unparsed voter lines: {', '.join(dv.leftover)[:200]}")
        if pv is None:
            reasons.append("no matching vote sentence in the minutes text")
        elif sorted((pv.a, pv.b)) != sorted((counts.jaa, counts.ei)) or pv.tyhja != counts.tyhja:
            reasons.append(
                f"minutes text says {pv.a}–{pv.b}, {pv.tyhja} blank; the PDF says "
                f"{counts.jaa} Jaa, {counts.ei} Ei, {counts.tyhja} Tyhjä"
            )
        if not dv.jaa_label or not dv.ei_label:
            reasons.append("missing Jaa/Ei proposal label")
        events.append(
            VoteEvent(
                ordinal=i + 1,
                jaa_label=dv.jaa_label,
                ei_label=dv.ei_label,
                counts=counts,
                ballots=ballots,
                result_text=pv.sentence if pv else None,
                source=VoteSource.pdf,
                source_url=pdf_url or item_url,
                needs_review=bool(reasons),
                review_reason="; ".join(reasons) or None,
            )
        )
    return events


# -- motions ------------------------------------------------------------------------------

MOTION = re.compile(
    r"^(?P<prop>(?:af\s+|von\s+)?[A-ZÅÄÖ][\w'’-]+)\s+(?P<sec>.+?)\s+kannattamana\s+"
    r"(?P<verb>teki|ehdotti|esitti)\b\s*(?P<rest>.*)$"
)


def parse_motions(lines: list[str]) -> list[Motion]:
    """ "Nevanlinna Aaltosen ym. kannattamana teki seuraavan toivomuksen:" + the next line, or
    "Partanen Hagerlundin kannattamana ehdotti, että asia palautetaan …". The proposer is printed by
    surname, seconders in the genitive as printed; resolving them is M5's job."""
    motions: list[Motion] = []
    for i, raw in enumerate(lines):
        line = re.sub(r"\s+", " ", raw).strip()
        m = MOTION.match(line)
        if not m:
            continue
        rest = m.group("rest").strip()
        # "teki seuraavan toivomuksen:" introduces the motion text on the next line
        text = lines[i + 1].strip() if rest.endswith(":") and i + 1 < len(lines) else rest
        low = line.lower()
        if "toivomu" in low or "ponsi" in low:
            kind = MotionKind.resolution
        elif "palaute" in low or "palautta" in low:
            kind = MotionKind.send_back
        elif "pöydälle" in low:
            kind = MotionKind.table
        else:
            kind = MotionKind.counter_proposal
        seconders = [
            s.strip()
            for s in re.split(r",|\s+ja\s+", re.sub(r"\bym\.?", "", m.group("sec")))
            if s.strip() and s.strip()[0].isupper()
        ]
        motions.append(
            Motion(
                kind=kind,
                proposer_ref=PersonRef(raw=m.group("prop")),
                seconder_refs=[PersonRef(raw=s) for s in seconders],
                text=text,
            )
        )
    return motions


def resolve_outcomes(motions: list[Motion], votes: list[VoteEvent]) -> None:
    """A vote whose Jaa label starts with the proposer's surname decides the motion."""
    for mo in motions:
        surname = mo.proposer_ref.raw.split()[0] if mo.proposer_ref.raw else ""
        for v in votes:
            if surname and v.jaa_label.split(" ")[0] == surname and v.counts.jaa != v.counts.ei:
                mo.outcome = Outcome.adopted if v.counts.jaa > v.counts.ei else Outcome.rejected
                break
