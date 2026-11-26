"""Split Oulu's committed items into summary, proposal and decision (one-off, 2026-11-26).

Oulu prints an item's own handling in a label column ("Päätösesitys …", "Päätös …") above the
presentation text ("Esittelyteksti"). Before `tweb.split_label_column`, none of it was read as a
section, so every Oulu item was one background section with the decision buried inside, and no
motions were found. The background text is kept in each item, so it can be split again without
fetching the documents. Motions are read from the decision text as `build_item` would; votes need
the vote reports, so they come with the next full crawl (`--window all`).

    python scripts/fix_oulu_sections.py [--dry-run]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from kunta import jsonio
from kunta.parsers import tweb as tp
from kunta.text import content_sha256, strip_pii

ROOT = Path(__file__).resolve().parent.parent


def resplit(item: dict, final: bool) -> bool:
    i = next(
        (k for k, s in enumerate(item["sections"]) if s["type"] == "background" and not s.get("heading")),
        None,
    )
    if i is None:
        return False
    doc = tp.ItemDoc(background=item["sections"][i]["text"].split("\n"))
    tp.split_label_column(doc)
    if not doc.blocks:
        return False
    sections, statements, deliberation = tp.item_sections(doc)
    item["sections"] = [
        *item["sections"][:i],
        *(jsonio._normalize(s) for s in sections),
        *item["sections"][i + 1 :],
    ]
    item["statements"] = [*item.get("statements", []), *(jsonio._normalize(s) for s in statements)]
    if final and not item.get("motions"):
        motions = tp.parse_motions(deliberation)
        for m in motions:
            m.text = strip_pii(m.text)
        item["motions"] = [jsonio._normalize(m) for m in motions]
    if doc.case_number and not item.get("case_number"):
        item["case_number"] = doc.case_number
    item["content_sha256"] = content_sha256(
        item.get("title") or "",
        *(s["text"] for s in item["sections"] + item["statements"]),
        *(m["text"] for m in item.get("motions", [])),
    )
    return True


def main() -> int:
    dry = "--dry-run" in sys.argv
    items = files = 0
    for path in sorted((ROOT / "data" / "oulu" / "meetings").glob("*/*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        final = doc["meeting"]["stage"] == "minutes"
        n = sum(resplit(it, final) for it in doc["items"])
        if n:
            items += n
            files += 1
            if not dry:
                jsonio.write(path, doc)
    print(f"{items} items split in {files} meetings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
