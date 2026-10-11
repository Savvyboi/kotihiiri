"""Text normalization, section classification and PII stripping (PLAN.md §9)."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from .models import SectionType

# Heading prefix (lowercase) → section type. Longest prefix wins. None = drop the section.
_HEADINGS: list[tuple[str, SectionType | None]] = [
    ("päätösehdotus", SectionType.proposal),
    ("esitys", SectionType.proposal),
    ("käsittely", SectionType.deliberation),
    ("päätöshistoria", SectionType.history),
    ("aikaisempi käsittely", SectionType.history),
    ("päätös", SectionType.decision),
    ("esittelijän perustelut", SectionType.background),
    ("perustelut", SectionType.background),
    ("selostus", SectionType.background),
    ("pöytäkirjalausuma", SectionType.statement),
    ("eriävä mielipide", SectionType.dissent),
    ("muutoksenhaku", None),
    ("muutoksenhakuohje", None),
    ("valitusosoitus", None),
    ("oikaisuvaatimusohje", None),
    ("lisätiedot", None),
    ("lisätietojen antaja", None),
    ("lisätietoja antaa", None),
    ("yhteystiedot", None),
]
_HEADINGS.sort(key=lambda h: len(h[0]), reverse=True)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def classify_heading(heading: str) -> SectionType | None:
    """Map a heading to a section type. Returns None for sections to drop (appeal, contact)."""
    h = nfc(heading).strip().lower()
    for prefix, kind in _HEADINGS:
        if h.startswith(prefix):
            return kind
    return SectionType.other


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(
    r"""
    (?<![\w-])              # not inside a code like KASKO-01-1029-25
    (?:\+358|0)              # international prefix or trunk 0
    [\s-]?\(?\d{1,3}\)?      # area / operator code
    (?:[\s-]?\d){5,9}        # subscriber number with optional separators
    \b
    """,
    re.VERBOSE,
)
_PHONE_LABEL = re.compile(r"\b(?:puh(?:elin)?\.?|p\.|tel\.?|gsm)\s*:?\s*(?=[\d+])", re.IGNORECASE)
_REDACTED = "[poistettu]"


def strip_pii(text: str) -> str:
    """Remove e-mail addresses, Finnish phone numbers and their "puhelin" labels."""
    text = _EMAIL.sub(_REDACTED, text)
    text = _PHONE_LABEL.sub("", text)
    text = _PHONE.sub(_REDACTED, text)
    # "[poistettu], [poistettu]" → one marker
    text = re.sub(r"(\[poistettu\][ \t,;/]*){2,}", _REDACTED + " ", text)
    return text


def contains_pii(text: str) -> bool:
    return bool(_EMAIL.search(text) or _PHONE.search(text))


def apply_takedown_strings(text: str, strings: list[str]) -> str:
    for s in strings:
        if s:
            text = text.replace(s, _REDACTED)
    return text


def collapse_ws(text: str) -> str:
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in nfc(text).splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def content_sha256(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(nfc(p).encode())
        h.update(b"\x00")
    return h.hexdigest()
