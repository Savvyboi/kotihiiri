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

from . import jsonio
from .config import DATA_DIR
from .ids import person_id
from .people import name_key, normalize_name

_OF = r"^(?:valtuuston )?"
_NTH = r"(?:\d\.|i+|ensimmäinen|toinen|kolmas)?\s*"
# role_text as printed on minutes → membership role; anything else (officials, youth reps,
# staff representatives, a council group's own chair) is not a membership.
_ROLES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(_OF + _NTH + r"(?:varapuheenjohtaja|vpj\.?$)", re.I), "vice_chair"),
    (re.compile(_OF + r"(?:puheenjohtaja|pj\.?$)|^ordförande", re.I), "chair"),
    (re.compile(r"^(?:varajäsen|varavaltuutettu|ersättare)", re.I), "deputy"),
    (re.compile(r"^(?:jäsen|valtuutettu|medlem|ledamot)", re.I), "member"),
]
_PARTICLES = {"af", "von", "de", "van", "der", "la", "di"}


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
        in accents ("Limnéll", "Limnell") are one person; the name is the form printed most often."""
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
            if role:
                self._get(a["person_ref"]["raw"]).see(m["body_id"], role, date)

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

    def add_parties(self, rows: Iterable[PartyRow]) -> tuple[int, list[str]]:
        """Attach each person's 2025 candidacy (party, result, votes). Persons are never created
        here (§8 step 6). A name is matched on its order-insensitive key; failing that, on a unique
        candidate with the same surname whose name tokens are a subset of the printed name or the
        other way round ("Mäkinen Juha J." ↔ "Mäkinen Juha"). A name two candidates share is
        never guessed. Returns (matched, names of councillors left without a party)."""
        by_key: dict[str, list[PartyRow]] = {}
        for r in rows:
            by_key.setdefault(name_key(r.name), []).append(r)
        by_fold: dict[str, list[PartyRow]] = {}
        for k, rs in by_key.items():
            by_fold.setdefault(_fold(k), []).extend(rs)
        tokens = {k: set(k.split()) for k in by_key}
        matched = 0
        for key, p in self.people.items():
            rs = by_key.get(key) or by_fold.get(_fold(key))
            if rs is None:
                mine = set(key.split())
                near = [
                    k
                    for k, t in tokens.items()
                    if (t <= mine or mine <= t) and len(t & mine) >= 2 and name_key(p.surname) in t
                ]
                rs = by_key[near[0]] if len(near) == 1 else None
            if rs and len(rs) == 1:
                p.election = rs[0]
                matched += 1
        missing = sorted(
            f"{p.surname} {p.first}"
            for p in self.people.values()
            if p.election is None and any(s.body_id == self.council_id for s in p.seen.values())
        )
        return matched, missing

    def to_json(self) -> dict:
        persons, memberships = [], []
        taken: set[str] = set()
        for key in sorted(
            self.people, key=lambda k: (self.people[k].surname.lower(), self.people[k].first.lower(), k)
        ):
            p = self.people[key]
            pid = person_id(self.city, p.surname, p.first, taken)
            taken.add(pid)
            name = f"{p.first} {p.surname}".strip()
            aliases = sorted(n for n in p.names if n != name)
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


def build(city: str, council_id: str | None, data_dir: Path = DATA_DIR) -> Roster:
    """Persons and memberships from the committed meeting files of one city."""
    roster = Roster(city, council_id)
    for path in sorted((data_dir / city / "meetings").glob("*/*.json")):
        mf = jsonio.read(path)
        roster.add_meeting(mf)
        if council_id:
            roster.add_group_votes(mf, council_id)
    return roster
