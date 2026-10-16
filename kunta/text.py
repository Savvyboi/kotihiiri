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
    (?!0\d\d-(?:19|20)\d\d-\d)  # nor a permit number like 049-2019-881 (municipality-year-n)
    (?:\+358|0)              # international prefix or trunk 0
    [\s-]?\(?\d{1,3}\)?      # area / operator code
    (?:[\s-]?\d){5,9}        # subscriber number with optional separators
    \b
    """,
    re.VERBOSE,
)
# Numbers that have a phone number's shape but are public ids, kept when the words just before
# them say so: a post number (virkanumero, vakanssinumero) or a diary number in any shape, and a
# property id (kiinteistötunnus, municipality-village-block-parcel, e.g. 098-416-12-34) after a
# word naming a property.
_ID_WORDS = re.compile(
    r"\b(?:virkanumero|vakanssinumero|vakanssi|tehtävänumero|diaarinumero|dnro|asianumero)\w*[\s:(]{1,4}$",
    re.IGNORECASE,
)
_PROPERTY_ID = re.compile(r"\d{1,3}-\d{1,3}-\d{1,4}-\d{1,4}")
_PROPERTY_WORDS = re.compile(
    r"\b(?:kiinteist\w*|kiint\.|tila(?:n|sta|lle|t)?|rn:o|määräal\w*|fastighet\w*)"
    r"[\s:(]{1,4}(?:rn:o|nro|tunnus)?[\s:]{0,3}$",
    re.IGNORECASE,
)
_UNBROKEN = re.compile(r"\+?\d+")


def _is_id(text: str, m: re.Match) -> bool:
    before = text[max(0, m.start() - 60) : m.start()]
    if _ID_WORDS.search(before):
        return True
    return bool(_PROPERTY_ID.match(text, m.start()) and _PROPERTY_WORDS.search(before))


def _phones(text: str, title: bool = False) -> list[re.Match]:
    """Phone-number matches that are not ids. In an item title an unbroken run of digits is an id
    (a post or case number): titles are agenda headings and never carry a person's number, and
    one written as such would have a label or separators."""
    return [
        m
        for m in _PHONE.finditer(text)
        if not _is_id(text, m) and not (title and _UNBROKEN.fullmatch(m.group(0)))
    ]


_PHONE_LABEL = re.compile(r"\b(?:puh(?:elin)?\.?|p\.|tel\.?|gsm)\s*:?\s*(?=[\d+])", re.IGNORECASE)
_REDACTED = "[poistettu]"


def strip_pii(text: str) -> str:
    """Remove e-mail addresses, Finnish phone numbers and their "puhelin" labels."""
    text = _EMAIL.sub(_REDACTED, text)
    text = _PHONE_LABEL.sub("", text)
    for m in reversed(_phones(text)):
        text = text[: m.start()] + _REDACTED + text[m.end() :]
    # "[poistettu], [poistettu]" → one marker
    text = re.sub(r"(\[poistettu\][ \t,;/]*){2,}", _REDACTED + " ", text)
    return text


def contains_pii(text: str, title: bool = False) -> bool:
    return bool(_EMAIL.search(text) or _phones(text, title))


def pii_shapes(text: str, title: bool = False) -> list[str]:
    """What matched, without the personal data: digits as 9, letters as x, plus the word before it
    when that word is lowercase (a label like "puh" or "kiinteistö", never a name). For logs."""
    out = []
    for m in [*_EMAIL.finditer(text), *_phones(text, title)]:
        shape = re.sub(r"\d", "9", re.sub(r"[^\W\d_]", "x", m.group(0)))
        before = text[: m.start()].split()[-1:] or [""]
        word = before[0] if before[0].islower() else ""
        out.append(f"{word} «{shape}»".strip())
    return out


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


# "Salassa pidettävä" as the title (Helsinki) or "{title} (Salassa pidettävä)" (Tampere).
_CONFIDENTIAL = re.compile(
    r"^\s*(?:salassa pidettävä|sekretessbelagd)\b|\(salassa pidettävä\)\s*$", re.IGNORECASE
)


def is_confidential(title: str | None) -> bool:
    """Items withheld under the Publicity Act are listed with this as their title and never get a
    public decision text, so an empty page is the final state, not a failed load."""
    return bool(title and _CONFIDENTIAL.search(title))
