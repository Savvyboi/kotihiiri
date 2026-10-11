"""Stable, human-readable IDs and slugs (PLAN.md §5.1)."""

from __future__ import annotations

import datetime as dt
import re
import unicodedata

_FINNISH_MAP = str.maketrans({"ä": "a", "ö": "o", "å": "a", "Ä": "a", "Ö": "o", "Å": "a"})


def slugify(text: str) -> str:
    """ASCII slug of a Finnish name: ä→a, ö→o, å→a, other accents stripped."""
    text = unicodedata.normalize("NFC", text).translate(_FINNISH_MAP)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def body_id(city: str, name_fi: str) -> str:
    return f"{city}/{slugify(name_fi)}"


def meeting_id(body: str, date: dt.date, same_day_index: int = 1) -> str:
    """`{body_id}/{YYYY-MM-DD}`, with `-2`, `-3` … for a second meeting the same day."""
    base = f"{body}/{date.isoformat()}"
    return base if same_day_index <= 1 else f"{base}-{same_day_index}"


def item_id(meeting: str, ordinal: int) -> str:
    if ordinal < 1:
        raise ValueError("ordinal is 1-based")
    return f"{meeting}/{ordinal}"


def person_id(city: str, surname: str, firstname: str, taken: set[str] | None = None) -> str:
    """`{city}/{surname-firstname}`, numeric suffix on collision with an id in `taken`."""
    base = f"{city}/{slugify(f'{surname} {firstname}')}"
    if not taken or base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def meeting_file_path(meeting: str) -> str:
    """data path of a meeting file relative to data/: `{city}/meetings/{yyyy}/{body}--{date}.json`."""
    city, body_slug, date = meeting.split("/")
    return f"{city}/meetings/{date[:4]}/{body_slug}--{date}.json"


def speeches_file_path(meeting: str) -> str:
    city, body_slug, date = meeting.split("/")
    return f"{city}/speeches/{body_slug}--{date}.json"
