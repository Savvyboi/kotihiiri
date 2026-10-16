"""City rosters: persons and memberships for data/{city}/people.json (PLAN.md §8).

Persons come only from roster sources: attendance lists on minutes (source 2), Helsinki's council
vote tables (source 1) and the elected-councillor list with party (source 4, `people_sources/`).
Names are joined by `people.name_key`, never by fuzzy match.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import jsonio
from .config import CONFIG_DIR, DATA_DIR
from .ids import person_id, slugify
from .people import name_key, normalize_name

_OF = r"^(?:valtuuston )?"
_NTH = r"(?:\d\.|i+|ensimmäinen|toinen|kolmas)?\s*"
# role_text as printed on minutes → membership role; anything else (officials, youth reps,
# staff representatives, a council group's own chair) is not a membership.
_ROLES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(_OF + _NTH + r"(?:varapuheenjohtaja|vpj\.?$|vice ?ordförande)", re.I), "vice_chair"),
    (re.compile(_OF + r"(?:puheenjohtaja|pj\.?$)|^ordförande", re.I), "chair"),
    (re.compile(r"^(?:varajäsen|varavaltuutettu|ersättare)", re.I), "deputy"),
    (re.compile(r"^(?:jäsen|valtuutettu|medlem|ledamot)", re.I), "member"),
]
_PARTICLES = {"af", "von", "de", "van", "der", "la", "di"}
# Start of the 2025–2029 council term, as the site's TERM_START.
TERM_START = "2025-06-01"
# Some minutes print the party after the name ("Virtanen Matti, KOK"); the name is what precedes it.
_PARTY_TAIL = re.compile(r"\s*,\s*[A-ZÅÄÖ]{2,5}\.?$")
# Attendance tables sometimes carry notes in the name column ("Kokouksessa tauko klo 17:06-17:35").
# Järvenpää prints a deputy's role after the name, sometimes without the closing bracket.
_ROLE_TAIL = re.compile(r"\s*\(?\s*(?:varajäsen|varavaltuutettu|ersättare)\s*\)?\s*$", re.I)
_NOT_A_NAME = re.compile(r"\d|^kokouksessa\b|^mötet\b", re.I)


def _fold(key: str) -> str:
    """Drop accents other than å, ä and ö, which are letters of their own in Finnish and Swedish:
    "limnéll" and "limnell" are one name, "makinen" and "mäkinen" are not."""
    out = []
    for ch in key:
        if ch in "åäö":
            out.append(ch)
        else:
            out.append(unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode() or ch)
    return "".join(out)


def role_of(role_text: str) -> str | None:
    t = role_text.strip()
    for rx, role in _ROLES:
        if rx.search(t):
            return role
    return None


def split_name(printed: str) -> tuple[str, str]:
    """(surname, first names) from "Sukunimi Etunimi(t)", the order on Espoo and Tampere minutes."""
    tokens = normalize_name(printed).split()
    i = 0
    while i < len(tokens) - 1 and tokens[i].lower() in _PARTICLES:
        i += 1
    return " ".join(tokens[: i + 1]), " ".join(tokens[i + 1 :])


@dataclass
class _Seen:
    body_id: str
    role: str
    first: dt.date
    last: dt.date
    group: str | None = None


@dataclass
class PartyRow:
    """One candidate of a party source: name ("Sukunimi Etunimi"), party abbreviation, result."""

    name: str
    party: str
    result: str  # elected | deputy | not_elected
    source: str
    votes: int | None = None
    surname: str | None = None
    first: str | None = None


@dataclass
class _Person:
    surname: str
    first: str
    names: Counter[str] = field(default_factory=Counter)
    seen: dict[tuple[str, str, str | None], _Seen] = field(default_factory=dict)
    election: PartyRow | None = None
    printed: set[str] = field(default_factory=set)

    def see(self, body_id: str, role: str, date: dt.date, group: str | None = None) -> None:
        k = (body_id, role, group)
        s = self.seen.get(k)
        if s is None:
            self.seen[k] = _Seen(body_id, role, date, date, group)
        else:
            s.first, s.last = min(s.first, date), max(s.last, date)


class Roster:
    def __init__(self, city: str, council_id: str | None = None) -> None:
        self.city = city
        self.council_id = council_id
        self.people: dict[str, _Person] = {}

    def _get(self, printed: str) -> _Person:
        """The person printed as "Sukunimi Etunimi", created on first sight. Forms that differ only
        in accents ("Limnéll", "Limnell") are one person; the name is the form printed most often.
        A form with the party after it is kept as an alias, so the site finds the printed name."""
        bare = _ROLE_TAIL.sub("", _PARTY_TAIL.sub("", printed))
        if bare != printed:
            p = self._get(bare)
            p.printed.add(normalize_name(printed))
            return p
        key = _fold(name_key(printed))
        p = self.people.get(key)
        if p is None:
            p = self.people[key] = _Person(*split_name(printed))
        form = normalize_name(printed)
        p.names[form] += 1
        best = max(p.names, key=lambda n: (p.names[n], n))
        if best == form:
            p.surname, p.first = split_name(form)
        return p

    def add_meeting(self, mf: dict) -> None:
        m = mf["meeting"]
        if m["stage"] != "minutes":
            return
        date = dt.date.fromisoformat(m["date"])
        for a in m.get("attendance", []):
            role = role_of(a.get("role_text", ""))
            # absent rows on Tampere minutes have no role text; they are members who did not attend
            if role is None and not a.get("present") and not a.get("role_text"):
                role = "member"
            raw = a["person_ref"]["raw"]
            if role and not _NOT_A_NAME.search(raw):
                self._get(raw).see(m["body_id"], role, date)

    def add_group_votes(self, mf: dict, council_id: str) -> None:
        """Helsinki: council vote tables print "Sukunimi, Etunimi" with the council group."""
        m = mf["meeting"]
        if m["stage"] != "minutes" or m["body_id"] != council_id:
            return
        date = dt.date.fromisoformat(m["date"])
        for item in mf["items"]:
            for v in item.get("votes", []):
                for b in v.get("ballots", []):
                    if not b.get("group_text"):
                        continue
                    raw = b["person_ref"]["raw"]
                    surname, _, first = raw.partition(",")
                    p = self._get(f"{surname.strip()} {first.strip()}" if first else raw)
                    p.see(m["body_id"], "member", date, b["group_text"])

    def add_parties(
        self, rows: Iterable[PartyRow], overrides: dict[str, str] | None = None
    ) -> tuple[int, list[str]]:
        """Attach each person's 2025 candidacy (party, result, votes). Persons are never created
        here (§8 step 6). A name is matched on its order-insensitive key; failing that, on a unique
        candidate whose surname is in the printed name and whose name tokens are a subset of the
        printed name or the other way round ("Mäkinen Juha J." ↔ "Mäkinen Juha", "Ari.M Laitinen"
        ↔ "Laitinen Ari"). A name two candidates share is never guessed. Several printed forms may
        take one candidacy ("Bibani Gashaw", "Gashaw Kaisa Bibani"): they are one person printed
        differently. `overrides` maps a printed name to its candidate's name in the list, for forms
        no rule can join ("Kauste Mika" → "Kauste Mikki"; config/people_overrides/, §8 source 5).
        Returns (matched, names of this term's councillors left without a party)."""
        rows = list(rows)
        by_key: dict[str, list[PartyRow]] = {}
        for r in rows:
            by_key.setdefault(name_key(r.name), []).append(r)
        forced: dict[str, PartyRow] = {}
        for printed, cand in (overrides or {}).items():
            rs = by_key.get(name_key(cand), [])
            if len(rs) != 1:
                raise ValueError(f"people override {printed!r}: {len(rs)} candidates named {cand!r}")
            forced[_fold(name_key(printed))] = rs[0]
        by_fold: dict[str, list[PartyRow]] = {}
        for k, rs in by_key.items():
            by_fold.setdefault(_fold(k), []).extend(rs)
        tokens = {k: set(k.split()) for k in by_key}
        exact: dict[str, PartyRow] = {}
        near: dict[str, PartyRow] = {}
        for key in self.people:
            if key in forced:
                exact[key] = forced[key]
                continue
            rs = by_key.get(key) or by_fold.get(_fold(key))
            if rs is not None:
                if len(rs) == 1:
                    exact[key] = rs[0]
                continue
            mine = set(key.split())
            close = [
                k
                for k, t in tokens.items()
                if (t <= mine or mine <= t)
                and len(t & mine) >= 2
                and len(by_key[k]) == 1
                and set(name_key(by_key[k][0].surname or by_key[k][0].name.split()[0]).split()) <= mine
            ]
            if len(close) == 1:
                near[key] = by_key[close[0]][0]
        matched = 0
        for key, row in [*exact.items(), *near.items()]:
            p = self.people[key]
            p.election = row
            matched += 1
            # The candidate list prints "Sukunimi Etunimi"; some minutes print first names first,
            # so take the surname from the list.
            if key in forced or (key in exact and _fold(name_key(row.name)) == _fold(key)):
                p.surname, p.first = split_name(row.name)
            elif key in near and row.surname:
                surname = set(name_key(row.surname).split())
                form = max(p.names, key=lambda n: (p.names[n], n))
                rest = [t for t in form.split() if name_key(t) not in surname]
                if rest:
                    p.surname, p.first = row.surname, " ".join(rest)
        missing = sorted(
            f"{p.surname} {p.first}"
            for p in self.people.values()
            if p.election is None
            and slugify(f"{p.surname} {p.first}")
            and any(
                s.body_id == self.council_id and s.last.isoformat() >= TERM_START for s in p.seen.values()
            )
        )
        return matched, missing

    def to_json(self) -> dict:
        persons, memberships = [], []
        taken: set[str] = set()
        for key in sorted(
            self.people, key=lambda k: (self.people[k].surname.lower(), self.people[k].first.lower(), k)
        ):
            p = self.people[key]
            if not slugify(f"{p.surname} {p.first}"):
                continue  # no letters or digits (a dash or stray mark in an attendance list)
            pid = person_id(self.city, p.surname, p.first, taken)
            taken.add(pid)
            name = f"{p.first} {p.surname}".strip()
            aliases = sorted(n for n in set(p.names) | p.printed if n != name)
            person = {
                "id": pid,
                "city": self.city,
                "name": name,
                "sort_name": f"{p.surname} {p.first}".strip(),
                "aliases": aliases,
            }
            if p.election:
                e = p.election
                person["party"] = e.party
                person["election"] = {"year": 2025, "party": e.party, "result": e.result, "source": e.source}
                if e.votes is not None:
                    person["election"]["votes"] = e.votes
            persons.append(person)
            for s in sorted(p.seen.values(), key=lambda s: (s.body_id, s.role, s.group or "", s.first)):
                ms = {
                    "person_id": pid,
                    "body_id": s.body_id,
                    "role": s.role,
                    "start": s.first.isoformat(),
                    "end": s.last.isoformat(),
                    "source": "vote_table" if s.group else "attendance",
                }
                if s.group:
                    ms["group"] = s.group
                memberships.append(ms)
        return {"persons": persons, "memberships": memberships}


def council_body_id(city: str, data_dir: Path = DATA_DIR) -> str | None:
    """The city council (valtuusto), not its question-hour body; as the site's councilBody()."""
    path = data_dir / city / "bodies.json"
    if not path.exists():
        return None
    councils = [b["id"] for b in jsonio.read(path) if b.get("kind") == "council" and b.get("included", True)]
    return next((c for c in councils if "kysely" not in c), councils[0] if councils else None)


def load_overrides(city: str, config_dir: Path = CONFIG_DIR) -> dict[str, str]:
    """config/people_overrides/{city}.yaml: `candidates: {printed name: candidate name}`."""
    path = config_dir / "people_overrides" / f"{city}.yaml"
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (raw.get("candidates") or {}).items()}


def build(city: str, council_id: str | None, data_dir: Path = DATA_DIR) -> Roster:
    """Persons and memberships from the committed meeting files of one city."""
    roster = Roster(city, council_id)
    for path in sorted((data_dir / city / "meetings").glob("*/*.json")):
        mf = jsonio.read(path)
        roster.add_meeting(mf)
        if council_id:
            roster.add_group_votes(mf, council_id)
    return roster
