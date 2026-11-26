"""Re-read Tampere's Jaa/Ei side labels from the committed vote headers (one-off, 2026-11-26).

Before `split_sides`, a header that named both sides on one line ("Esittelijän päätösehdotus =
JAA, Suomen muutosehdotus = EI") left the labels as the bare "Jaa"/"Ei", or put both sides in
the Ei label. The header text is kept in each vote's `result_text`, so the labels can be read
again without fetching the pages.

    python scripts/fix_tampere_vote_sides.py [--dry-run]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from kunta import jsonio
from kunta.parsers.votes_casem import split_sides

ROOT = Path(__file__).resolve().parent.parent
RESULT = re.compile(r":\s*äänesty(?:ksen|sesityksen) tulos\b", re.IGNORECASE)


def fixed(vote: dict) -> tuple[str, str] | None:
    if vote["jaa_label"] not in ("", "Jaa") and " JAA" not in vote["ei_label"]:
        return None
    header = RESULT.split(vote.get("result_text") or "", maxsplit=1)[0]
    # "A JAA, B EI" read as one Ei label lost its trailing " EI"
    return split_sides(vote["ei_label"] + " EI") or split_sides(header)


def main() -> int:
    dry = "--dry-run" in sys.argv
    changed = 0
    for path in sorted((ROOT / "data" / "tampere" / "meetings").glob("*/*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        touched = False
        for item in doc["items"]:
            for vote in item["votes"]:
                sides = fixed(vote)
                if sides and sides != (vote["jaa_label"], vote["ei_label"]):
                    print(f"{item['id']} #{vote['ordinal']}: {sides[0]!r} / {sides[1]!r}")
                    vote["jaa_label"], vote["ei_label"] = sides
                    touched = True
                    changed += 1
        if touched and not dry:
            jsonio.write(path, doc)
    print(f"{changed} votes relabelled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
