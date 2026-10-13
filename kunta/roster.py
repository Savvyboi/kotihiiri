"""City rosters: persons and memberships for data/{city}/people.json (PLAN.md §8).

Persons come only from roster sources: attendance lists on minutes (source 2), Helsinki's council
vote tables (source 1) and the elected-councillor list with party (source 4, `people_sources/`).
Names are joined by `people.name_key`, never by fuzzy match.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from . import jsonio
from .config import DATA_DIR
from .ids import person_id
from .people import name_key, normalize_name

TERM_START = dt.date(2025, 6, 1)

# role_text as printed on minutes → membership role; anything else (officials, youth reps,
# staff representatives) is not a membership.
_ROLES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(valtuuston |kaupunginhallituksen )?(\d\.|i+|ensimmäinen|toinen|kolmas)?\s*varapuheenjohtaja|vpj\.?$|^\d\.\s*vpj", re.I), "vice_chair"),
    (re.compile(r"^(valtuuston |kaupunginhallituksen )?puheenjohtaja|^valtuuston pj\.?$|^ordförande", re.I), "chair"),
    (re.compile(r"^(varajäsen|varavaltuutettu|ersättare)", re.I), "deputy"),
    (re.compile(r"^(jäsen|valtuutettu|medlem|ledamot)", re.I), "member"),
]
_PARTICLES = {"af", "von", "de", "van", "der", "la", "di"}


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
class _Person:
    surname: str
    first: str
    names: set[str] = field(default_factory=set)
    seen: dict[tuple[str, str, str | None], _Seen] = field(default_factory=dict)
    party: str | None = None
    elected: bool | None = None
    party_source: str | None = None

    def see(self, body_id: str, role: str, date: dt.date, group: str | None = None) -> None:
        k = (body_id, role, group)
        s = self.seen.get(k)
        if s is None:
            self.seen[k] = _Seen(body_id, role, date, date, group)
        else:
            s.first, s.last = min(s.first, date), max(s.last, date)


@dataclass
class PartyRow:
    """One row of a party source: a person, their party abbreviation, and whether elected."""

    name: str  # any order; joined by name_key
    party: str
    elected: bool
    source: str
    surname: str | None = None
    first: str | None = None


class Roster:
    def __init__(self, city: str) -> None:
        self.city = city
        self.people: dict[str, _Person] = {}

    def _get(self, printed: str, *, surname_first: bool = True) -> _Person:
        key = name_key(printed)
        p = self.people.get(key)
        if p is None:
            if surname_first:
                surname, first = split_name(printed)
            else:
                *first, surname = normalize_name(printed).split()
                first = " ".join(first)
            p = self.people[key] = _Person(surname, first)
        p.names.add(normalize_name(printed))
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

    def add_parties(self, rows: Iterable[PartyRow]) -> tuple[int, int]:
        """Attach party and elected flag to persons already on the roster; add elected councillors
        not yet seen (they sit on the council even before the first minutes we hold).
        Returns (matched, added)."""
        rows = list(rows)
        by_key: dict[str, list[PartyRow]] = {}
        for r in rows:
            by_key.setdefault(name_key(r.name), []).append(r)
        matched = added = 0
        for key, rs in by_key.items():
            if len(rs) != 1:
                continue  # a name shared by two candidates in one city is never guessed (§8 step 4)
            r = rs[0]
            p = self.people.get(key)
            if p is None:
                if not r.elected:
                    continue  # only councillors are added from this source
                p = self.people[key] = _Person(r.surname or split_name(r.name)[0], r.first or split_name(r.name)[1])
                p.names.add(normalize_name(r.name))
                added += 1
            else:
                matched += 1
            p.party, p.elected, p.party_source = r.party, r.elected, r.source
        return matched, added

    def to_json(self) -> dict:
        persons, memberships = [], []
        taken: set[str] = set()
        for key in sorted(self.people, key=lambda k: (self.people[k].surname.lower(), self.people[k].first.lower(), k)):
            p = self.people[key]
            pid = person_id(self.city, p.surname, p.first, taken)
            taken.add(pid)
            name = f"{p.first} {p.surname}".strip()
            aliases = sorted(n for n in p.names if n != name)
            person = {"id": pid, "city": self.city, "name": name, "sort_name": f"{p.surname} {p.first}".strip(),
                      "aliases": aliases}
            if p.party:
                person["party"] = p.party
                person["party_source"] = p.party_source
            if p.elected is not None:
                person["elected"] = p.elected
            persons.append(person)
            for s in sorted(p.seen.values(), key=lambda s: (s.body_id, s.role, s.group or "", s.first)):
                ms = {"person_id": pid, "body_id": s.body_id, "role": s.role, "start": s.first.isoformat(),
                      "end": s.last.isoformat(), "source": "vote_table" if s.group else "attendance"}
                if s.group:
                    ms["group"] = s.group
                memberships.append(ms)
        return {"persons": persons, "memberships": memberships}


def build(city: str, council_id: str | None, party_rows: Iterable[PartyRow] = (), data_dir: Path = DATA_DIR) -> Roster:
    roster = Roster(city)
    for path in sorted((data_dir / city / "meetings").glob("*/*.json")):
        mf = jsonio.read(path)
        roster.add_meeting(mf)
        if council_id:
            roster.add_group_votes(mf, council_id)
    roster.add_parties(party_rows)
    return roster
