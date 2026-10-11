"""Name normalization and resolution (PLAN.md §8).

Never creates a Person from a fuzzy match. Unresolved refs keep `person_id = None`
and are appended to data/review/unresolved_names.csv by the caller.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import PersonRef

TITLES = [
    "apulaispormestari",
    "varapuheenjohtaja",
    "puheenjohtaja",
    "pormestari",
    "valtuutettu",
    "varavaltuutettu",
    "ledamoten",
    "ledamot",
    "varajäsen",
    "jäsen",
    "ordförande",
    "biträdande borgmästare",
    "borgmästare",
]
_TITLE_RE = re.compile(r"^(?:(?:" + "|".join(TITLES) + r")\b\s*)+", re.IGNORECASE)
_PAREN_TAIL = re.compile(r"\s*\([^)]*\)\s*$")
FUZZY_THRESHOLD = 92


def normalize_name(raw: str) -> str:
    """NFC, collapse whitespace, strip leading titles and trailing parenthesized notes."""
    s = unicodedata.normalize("NFC", raw)
    s = re.sub(r"\s+", " ", s).strip()
    while True:
        stripped = _PAREN_TAIL.sub("", s)
        if stripped == s:
            break
        s = stripped
    s = _TITLE_RE.sub("", s).strip()
    return s


def name_key(raw: str) -> str:
    """Order-insensitive key: sorted lowercase tokens without punctuation.

    "Sukunimi, Etunimi", "Etunimi Sukunimi" and "Sukunimi Etunimi" share a key.
    """
    s = normalize_name(raw).lower()
    tokens = re.findall(r"[\w]+(?:-[\w]+)*", s)
    return " ".join(sorted(tokens))


@dataclass(frozen=True)
class Candidate:
    person_id: str
    names: tuple[str, ...]  # display name + aliases


def resolve(raw: str, candidates: list[Candidate]) -> PersonRef:
    """Resolve a printed name against persons with an overlapping membership (§8 steps 1–5)."""
    key = name_key(raw)
    exact = {c.person_id for c in candidates if any(name_key(n) == key for n in c.names)}
    if len(exact) == 1:
        return PersonRef(raw=raw, person_id=exact.pop(), confidence=1.0)
    if len(exact) > 1:
        return PersonRef(raw=raw)

    scored: list[tuple[float, str]] = []
    for c in candidates:
        best = max(fuzz.token_set_ratio(key, name_key(n)) for n in c.names)
        scored.append((best, c.person_id))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= FUZZY_THRESHOLD and (len(scored) == 1 or scored[1][0] < scored[0][0]):
        return PersonRef(raw=raw, person_id=scored[0][1], confidence=round(scored[0][0] / 100, 3))
    return PersonRef(raw=raw)
