"""Votes from the minutes text alone, in the many ways municipalities word them (PLAN.md §7.6).

Most registry municipalities publish no vote list that we read: the minutes sentence is the
record. The wording differs from place to place, but it is built from a few parts, which this
module finds in text order and assembles into votes:

* a side with a choice and a count, often with the voters' names in brackets:
  "annettiin 7 JAA-ääntä (Ahonen, Heikkilä-Halkola, …) ja 4 EI-ääntä (Kiiskinen, …)",
  "4 'JAA' -ääntä (…), 6 'EI' -ääntä (…) ja yksi 'TYHJÄ' (…)", "32 kpl JAA-ääntä";
* a named side with a count: "kaupunginjohtajan pohjaesitys sai 7 JAA-ääntä (…)",
  "Pietilän vastaesitys sai 11 ääntä", "palautuksen puolesta äänesti 10 jäsentä",
  "kaupunginhallituksen ehdotusta kannatti 38 valtuutettua", "motförslaget fick 6 röster (…)";
* voters by choice after the counts: "JAA äänestivät Saara Huhmarniemi ja Sanni Jäppinen.";
* blank and absent counts: "1 tyhjä ääni", "tyhjää äänesti 2 valtuutettua", "1 poissa";
* a bare result: "äänin 6-4", "äänin 11 (…) 2 (…)", "tulokseksi tulleen 9–2", and the Espoo
  form "kymmenellä äänellä kahta ääntä vastaan";
* the voting proposal that says what Jaa and Ei mean: "ne, jotka kannattavat esittelijän
  päätösehdotusta, äänestävät jaa ja ne, jotka kannattavat Kirsi Olkkosen muutosesitystä,
  äänestävät ei", "pohjaehdotus on 'JAA' ja … muutosehdotus on 'EI'".

A side whose choice is not printed takes Jaa if the vote has none yet, else Ei. A bare result
that repeats the current vote's counts is the same vote; otherwise it is a vote of its own, kept
with `needs_review` because the text does not say which count was Jaa. Names become ballots only
when their number equals the side's count. Secret ballots give counts and no names; elections of
a person ("Juho Lukkari sai 7 ääntä") are not read as votes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Ballot, Choice, Counts, PersonRef, VoteEvent, VoteSource
from .votes_cloudmeeting import NUMBER_WORDS

# -- normalisation ------------------------------------------------------------------------------

_MORE_WORDS = {
    "neljätoista": 14,
    "viisitoista": 15,
    "kuusitoista": 16,
    "seitsemäntoista": 17,
    "kahdeksantoista": 18,
    "yhdeksäntoista": 19,
    "kaksikymmentä": 20,
}
WORDS = NUMBER_WORDS | _MORE_WORDS
_WORD_RE = "|".join(sorted(WORDS, key=len, reverse=True))
VOTE_WORD = r"(?:kpl\s+)?(?:jaa|ei|tyhj|ään|jäsen|valtuut|röst|ollessa|poissa)"


def normalize(text: str) -> str:
    t = re.sub(r"[‘’'\"“”´`]", "", text)
    t = t.replace("EÍ", "EI").replace("–", "-").replace("—", "-").replace("­", "")
    t = re.sub(r"\(\s*kpl\s*\)", "kpl", t)
    # "kuusi (6)", "kaksikymmentäkaksi (22)": the digits win.
    t = re.sub(
        r"\b[A-Za-zÅÄÖåäö]+\s*\((\d+)\)", lambda m: m.group(1) if _numberish(m.group(0)) else m.group(0), t
    )
    t = re.sub(
        rf"\b({_WORD_RE})\b(?=\s+{VOTE_WORD})", lambda m: str(WORDS[m.group(1).lower()]), t, flags=re.I
    )
    t = re.sub(r"[ \t]+", " ", t)
    return t


def _numberish(s: str) -> bool:
    word = s.split("(")[0].strip().lower()
    return word in WORDS or bool(re.search(r"(kymmen|toista|sata)", word))


# -- events -------------------------------------------------------------------------------------

NAMES = r"(?:\s*\((?P<names>[^()\d]{2,1500})\))?"
CHOICE = r"(?P<c>jaa|ei|tyhjä|tyhjiä|tyhjää)"
AAN = r"(?:\s*-\s*|\s+|-)?(?P<aan>ään\w*)?"
# Text before a named side: the part of the sentence after its last connector.
LABEL = r"(?P<label>[^.;:!?()\n]{2,200}?)"
SIDE_WORDS = r"(?:esity|ehdotu|pohja|jatkami|palaut|pöydälle|käsittel|ponne|ponsi|lisäy|hylkäy)"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # "X:n puolesta annettiin 6 jaa-ääntä (…)", "palautuksen puolesta äänesti 10 jäsentä",
    # "muutosesitystä vastaan annettiin 3 ääntä (…)", "sitä vastaan 9 jäsentä"
    (
        "named",
        re.compile(
            LABEL + r"\s+(?P<pv>puolesta|vastaan)\s+(?:annettiin\s+|äänesti\s+|äänestivät\s+)?(?P<n>\d+)\s+"
            r"(?:(?P<c>jaa|ei)\s*-?\s*ään\w*|jäsen\w*|valtuute\w*|ään\w*)" + NAMES,
            re.I,
        ),
    ),
    # "… ja 9 jäsentä äänesti sitä vastaan"
    (
        "against",
        re.compile(
            r"(?P<n>\d+)\s+(?:jäsen\w*|valtuute\w*)\s+äänesti\w*\s+(?:sitä\s+|niitä\s+)?vastaan", re.I
        ),
    ),
    # "esittelijän ehdotusta kannattivat Simo Grönroos, …, yhteensä kahdeksan ääntä"
    (
        "named",
        re.compile(
            LABEL
            + r"\s+(?:\((?:jaa|ei)\)\s+)?kannattivat\s+(?P<names>[^.()\d]{2,1500}?),?"
            + r"\s+yhteensä\s+(?P<n>\d+)\s+ään\w*",
            re.I,
        ),
    ),
    # "kaupunginjohtajan pohjaesitys sai 7 JAA-ääntä (…)", "Pietilän vastaesitys sai 11 ääntä",
    # "jäsen Palorannan esitys 7 ääntä"
    (
        "named",
        re.compile(
            LABEL
            + r"\s+(?:sai(?:vat)?|sain)\s+(?P<n>\d+)\s+(?:kpl\s+)?(?:(?P<c>JAA|EI)\s*-?\s*)?ään\w*"
            + NAMES,
            re.I,
        ),
    ),
    (
        "named_bare",
        re.compile(LABEL + r"\s+(?P<n>\d+)\s+(?:kpl\s+)?(?:(?P<c>JAA|EI)\s*-?\s*)?ääntä" + NAMES, re.I),
    ),
    # "kaupunginhallituksen ehdotusta kannatti 38 valtuutettua"
    ("named", re.compile(LABEL + r"\s+kannatti\s+(?P<n>\d+)\s+(?:valtuute\w*|jäsen\w*)" + NAMES, re.I)),
    # Swedish: "motförslaget fick 6 röster (…) och beredningen 2 röster (…)"
    ("named_sv", re.compile(LABEL + r"\s+(?:fick\s+)?(?P<n>\d+)\s+röster" + NAMES, re.I)),
    # "9 JAA-ääntä (…)", "1 tyhjä ääni", "4 JAA -ääntä", "1 TYHJÄ (…)"
    ("choice", re.compile(r"(?P<n>\d+)\s*(?:kpl\s*)?" + CHOICE + r"\b" + AAN + NAMES, re.I)),
    # A table row: "JAA 7", "Jaa-äänet: 11", "EI-ääniä 4 kpl"
    (
        "choice",
        re.compile(
            r"(?m)^\s*(?P<c>JAA|EI|TYHJÄ|TYHJIÄ|Jaa|Ei|Tyhjä)(?:\s*-?\s*ään\w*)?\s*[:=]?\s*(?P<n>\d+)\b(?:\s*kpl)?"
            + NAMES
        ),
    ),
    # Bare results.
    (
        "pair",
        re.compile(
            r"äänin\s+(?P<a>\d+)"
            + NAMES.replace("names", "na")
            + r"\s*-?\s*(?P<b>\d+)\b"
            + NAMES.replace("names", "nb"),
            re.I,
        ),
    ),
    ("pair", re.compile(r"tulokse(?:na|ksi)\s+(?:tulleen\s+|on\s+)?(?P<a>\d+)\s*-\s*(?P<b>\d+)\b", re.I)),
    (
        "pair",
        re.compile(
            r"(?P<a>\d+)\s+äänellä\s+(?P<b>\d+)\s+(?:ääntä\s+)?(?:\d+\s+ollessa\s+poissa\s+)?vastaan", re.I
        ),
    ),
    ("tyhja", re.compile(r"tyhjää\s+äänesti\s+(?P<n>\d+)|(?P<n2>\d+)\s+(?:\w+\s+)?äänesti\s+tyhjää", re.I)),
    (
        "poissa",
        re.compile(
            r"(?P<n>\d+)\s+(?:kpl\s+)?(?:\w+\s+)?(?:poissa|ollessa\s+poissa)\b|poissa\s+oli\s+(?P<n2>\d+)",
            re.I,
        ),
    ),
    # "JAA äänestivät Saara Huhmarniemi ja Sanni Jäppinen."
    ("voters", re.compile(r"\b(?P<c>JAA|EI|TYHJÄÄ)\s+äänestivät\s+(?P<names>[^.\n]+)")),
    # Voting proposal: what Jaa and Ei mean.
    (
        "proposal",
        re.compile(
            r"kannatta\w*\s+(?P<jaa>[^.;]{3,200}?),?\s+äänestä\w*\s+jaa\b.{0,40}?kannatta\w*\s+(?P<ei>[^.;]{3,200}?),?\s+äänestä\w*\s+ei\b",
            re.I | re.S,
        ),
    ),
    (
        "proposal",
        re.compile(r"(?P<jaa>[^.;:,]{3,160}?)\s+on\s+JAA\s+ja\s+(?P<ei>[^.;:]{3,160}?)\s+on\s+EI\b", re.S),
    ),
    (
        "proposal",
        re.compile(
            r"(?P<jaa>[^.;:,]{3,160}?)\s+(?:kannalla\s+olevat|kannattajat|kannattavat)\s+äänestävät\s+JAA\s+ja\s+"
            r"(?P<ei>[^.;:]{3,160}?)\s+(?:kannalla\s+olevat|kannattajat|kannattavat|puoltavat)\s+äänestävät\s+EI\b",
            re.S,
        ),
    ),
]

# A person elected in a ballot is not a side of a vote.
_CONNECTOR = re.compile(
    r"^.*(?:äänestyksessä|äänestyksessa|annettiin|äänestys|tuloksena|tulos|siten|että|\bja\b|\boch\b|,|\bkun\b)\s+",
    re.I,
)


def _clean_label(raw: str) -> str:
    label = _CONNECTOR.sub("", raw.strip()).strip(" -")
    return (label[:1].upper() + label[1:]) if label and len(label) <= 160 else ""


@dataclass
class _Event:
    kind: str
    start: int
    end: int
    m: re.Match[str]


def _events(text: str) -> list[_Event]:
    taken: list[tuple[int, int]] = []
    out: list[_Event] = []
    for kind, pat in PATTERNS:
        for m in pat.finditer(text):
            s, e = m.span()
            if kind == "proposal":
                out.append(_Event(kind, s, e, m))  # proposals may overlap counts; they only set labels
                continue
            if kind.startswith("named"):
                # A named side's label must name a proposal, not a person being elected; "puolesta"
                # and "vastaan" only occur in votes.
                if not (
                    kind == "named_sv"
                    or m.groupdict().get("pv")
                    or re.search(SIDE_WORDS, _clean_label(m.group("label")), re.I)
                ):
                    continue
                s = m.start("label")
            if any(s < te and ts < e for ts, te in taken):
                continue
            taken.append((s, e))
            out.append(_Event(kind, s, e, m))
    return sorted(out, key=lambda ev: (ev.start, ev.kind != "proposal"))


# -- assembly -----------------------------------------------------------------------------------

CHOICES = {
    "jaa": Choice.jaa,
    "ei": Choice.ei,
    "tyhjä": Choice.tyhja,
    "tyhjiä": Choice.tyhja,
    "tyhjää": Choice.tyhja,
}


def split_names(raw: str | None) -> list[str]:
    if not raw:
        return []
    text = re.sub(r"\([^)]*\)", "", raw).strip().rstrip(".")
    names = [n.strip(" .") for n in re.split(r",\s*|\s+ja\s+|\s+och\s+", text)]
    names = [n for n in names if n]
    if any(re.search(r"\d", n) or len(n.split()) > 4 or not n[:1].isupper() for n in names):
        return ["?"]  # not a name list; never matches a count
    return names


@dataclass
class _Vote:
    counts: dict[Choice, int] = field(default_factory=dict)
    names: dict[Choice, list[str]] = field(default_factory=dict)
    labels: dict[Choice, str] = field(default_factory=dict)
    sentences: list[str] = field(default_factory=list)
    bare: bool = False

    def full(self) -> bool:
        return Choice.jaa in self.counts and Choice.ei in self.counts


WON_CHOICE = re.compile(r"\b(?P<c>JAA|EI)[ -]?äänet\s+voittivat", re.I)
WON = re.compile(
    r"(?P<w>[^.;:]{2,160}?)\s+voitti\s+(?:äänestyksessä\s+)?(?P<l>[^.;:]{2,160}?)\s+(?:äänestyksessä\s+)?äänin",
    re.I,
)
LOST = re.compile(
    r"(?P<l>[^.;:]{2,160}?)\s+hävisi\s+(?:äänestyksessä\s+)?(?P<w>[^.;:]{2,160}?)\s+äänin", re.I
)


def _sides_of_result(v: _Vote, sentence: str) -> None:
    """A bare result written with its winner: "EI äänet voittivat … äänin 6 - 5" says which count
    was Ei; "X voitti Y:n äänin 8 (…) 5 (…)" and "Y hävisi X:lle äänin …" name both sides, the
    winner's count first."""
    a, b = v.counts[Choice.jaa], v.counts[Choice.ei]
    m = WON_CHOICE.search(sentence)
    if m and a != b:
        won = Choice.jaa if m.group("c").lower() == "jaa" else Choice.ei
        lost = Choice.ei if won == Choice.jaa else Choice.jaa
        big, small = (a, b) if a > b else (b, a)
        names = {
            big: v.names.get(Choice.jaa if a > b else Choice.ei),
            small: v.names.get(Choice.ei if a > b else Choice.jaa),
        }
        v.counts[won], v.counts[lost] = big, small
        v.names = {k: n for k, n in ((won, names[big]), (lost, names[small])) if n}
        v.bare = False
        return
    m = WON.search(sentence) or LOST.search(sentence)
    if m:
        w, lo = _clean_label(m.group("w")), _clean_label(m.group("l"))
        if w and lo:
            v.labels = {Choice.jaa: w, Choice.ei: lo}


def _is_count(m: re.Match[str]) -> bool:
    """A choice word counts as a vote count when written as one: "7 JAA", "9 jaa-ääntä",
    "4 ei (Name, …)", or a table row."""
    return bool(
        m.re.pattern.startswith("(?m)")
        or m.groupdict().get("aan")
        or m.group("c").isupper()
        or m.groupdict().get("names")
    )


def _sentence_span(text: str, start: int, end: int) -> tuple[int, str]:
    s = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    e_dot, e_nl = text.find(". ", end), text.find("\n", end)
    ends = [x for x in (e_dot, e_nl) if x >= 0]
    e = min(ends) + 1 if ends else len(text)
    return s + 1, text[s + 1 : e].strip()


def _sentence(text: str, start: int, end: int) -> str:
    return _sentence_span(text, start, end)[1]


def parse(lines: list[str], *, item_url: str) -> list[VoteEvent]:
    text = normalize("\n".join(ln for ln in lines if ln.strip()))
    votes: list[_Vote] = []
    cur: _Vote | None = None
    pending: dict[Choice, str] = {}
    first_seen: dict[str, int] = {}  # sentence text -> where it first occurs

    def new_vote() -> _Vote:
        nonlocal pending
        v = _Vote(labels=dict(pending))
        pending = {}
        votes.append(v)
        return v

    def note(v: _Vote, ev: _Event) -> None:
        sent = _sentence(text, ev.start, ev.end)
        if sent not in v.sentences:
            v.sentences.append(sent)

    for ev in _events(text):
        m = ev.m
        at, sent = _sentence_span(text, ev.start, ev.end)
        # The same sentence printed twice (deliberation and decision) is one vote, not two.
        if first_seen.setdefault(sent, at) != at:
            continue
        if ev.kind == "proposal":
            pending = {Choice.jaa: _clean_label(m.group("jaa")), Choice.ei: _clean_label(m.group("ei"))}
            pending = {k: v for k, v in pending.items() if v}
            continue
        if ev.kind in ("named", "named_bare", "named_sv", "choice", "against"):
            n = int(m.group("n"))
            c = (m.groupdict().get("c") or "").lower()
            choice = CHOICES.get(c)
            if ev.kind == "choice" and choice in (Choice.jaa, Choice.ei) and not _is_count(m):
                continue  # "6 ei …" in running prose is not a count
            if choice == Choice.tyhja:
                if cur is not None and Choice.tyhja not in cur.counts:
                    cur.counts[Choice.tyhja] = n
                    if m.groupdict().get("names"):
                        cur.names[Choice.tyhja] = split_names(m.group("names"))
                    note(cur, ev)
                continue
            if (
                cur is None
                or cur.bare
                or (choice is not None and choice in cur.counts)
                or (choice is None and cur.full())
            ):
                cur = new_vote()
            if choice is None:
                choice = Choice.jaa if Choice.jaa not in cur.counts else Choice.ei
                if choice in cur.counts:
                    cur = new_vote()
            cur.counts[choice] = n
            if m.groupdict().get("names"):
                cur.names[choice] = split_names(m.group("names"))
            if ev.kind == "against":
                cur.labels.setdefault(choice, "Vastaan")
            if ev.kind.startswith("named"):
                label = _clean_label(m.group("label"))
                if ev.kind == "named" and m.groupdict().get("pv"):
                    label = f"{label} {m.group('pv')}" if label else ""
                if label:
                    cur.labels[choice] = label
            note(cur, ev)
        elif ev.kind in ("tyhja", "poissa"):
            n = int(m.group("n") or m.group("n2"))
            ch = Choice.tyhja if ev.kind == "tyhja" else Choice.poissa
            if cur is not None and ch not in cur.counts:
                cur.counts[ch] = n
                note(cur, ev)
        elif ev.kind == "voters":
            ch = CHOICES[m.group("c").lower()]
            names = split_names(m.group("names"))
            if cur is None:
                continue
            if ch not in cur.names:
                cur.names[ch] = names
                cur.counts.setdefault(ch, len(names))
                note(cur, ev)
        elif ev.kind == "pair":
            a, b = int(m.group("a")), int(m.group("b"))
            if cur is not None and not cur.bare and len(cur.counts.keys() & {Choice.jaa, Choice.ei}) == 1:
                # One side was written out, the result names both: the other side is the rest.
                have = Choice.jaa if Choice.jaa in cur.counts else Choice.ei
                rest = [a, b]
                if cur.counts[have] in rest:
                    rest.remove(cur.counts[have])
                    cur.counts[Choice.ei if have == Choice.jaa else Choice.jaa] = rest[0]
                    note(cur, ev)
                    continue
            if (
                cur is not None
                and cur.full()
                and sorted((a, b)) == sorted((cur.counts[Choice.jaa], cur.counts[Choice.ei]))
            ):
                note(cur, ev)
                gd = m.groupdict()
                for key, n in (("na", a), ("nb", b)):
                    if gd.get(key):
                        for ch in (Choice.jaa, Choice.ei):
                            if cur.counts[ch] == n and ch not in cur.names:
                                cur.names[ch] = split_names(gd[key])
                                break
                continue
            cur = new_vote()
            cur.bare = True
            cur.counts[Choice.jaa], cur.counts[Choice.ei] = a, b
            gd = m.groupdict()
            if gd.get("na"):
                cur.names[Choice.jaa] = split_names(gd["na"])
            if gd.get("nb"):
                cur.names[Choice.ei] = split_names(gd["nb"])
            _sides_of_result(cur, sent)
            note(cur, ev)

    events: list[VoteEvent] = []
    for v in votes:
        if not v.full() or (v.counts[Choice.jaa] == 0 and v.counts[Choice.ei] == 0):
            continue
        reasons: list[str] = []
        if v.bare and not (v.labels.get(Choice.jaa) and v.labels.get(Choice.ei)):
            reasons.append("the minutes give only the result, not which count was Jaa")
        ballots: list[Ballot] = []
        named = set()
        for ch in Choice:
            names = v.names.get(ch)
            if not names:
                continue
            if len(names) != v.counts.get(ch, 0):
                reasons.append(f"{ch.value}: {len(names)} names for {v.counts.get(ch, 0)} votes in the text")
                continue
            if named & set(names):
                reasons.append("a name is listed on two sides")
                ballots = []
                break
            named |= set(names)
            ballots.extend(Ballot(person_ref=PersonRef(raw=n), choice=ch) for n in names)
        events.append(
            VoteEvent(
                ordinal=len(events) + 1,
                jaa_label=v.labels.get(Choice.jaa, ""),
                ei_label=v.labels.get(Choice.ei, ""),
                counts=Counts(
                    jaa=v.counts[Choice.jaa],
                    ei=v.counts[Choice.ei],
                    tyhja=v.counts.get(Choice.tyhja, 0),
                    poissa=v.counts.get(Choice.poissa, 0),
                ),
                ballots=ballots,
                result_text=" ".join(v.sentences)[:800] or None,
                source=VoteSource.html,
                source_url=item_url,
                needs_review=bool(reasons),
                review_reason="; ".join(reasons) or None,
            )
        )
    return events
