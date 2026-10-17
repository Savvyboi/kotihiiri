"""Vote coverage per municipality: which minutes items mention a vote, which have one.

    python scripts/votes_audit.py [--samples N] city [city ...]

Reads data/{city}/meetings/*/*.json. An item "mentions a vote" when its deliberation or decision
text has a vote sentence (äänestys, äänin, jaa-ääni, röstning …). Prints, per city, the counts and
up to N items that mention a vote but have none, with the sentence and the attachment titles, so a
parser gap can be read from the workflow log without fetching any page.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

VOTE_TEXT = re.compile(
    r"äänestyks|äänestettiin|äänestys\b|äänin\s+\d|\d+\s*[-–]\s*\d+\s+äänin|jaa[- ]?ää|ei[- ]?ää|"
    r"äänellä\s+\S+\s+(?:ääntä\s+)?vastaan|omröstning|röstade|röster\s+mot",
    re.IGNORECASE,
)
# Phrases that say no vote happened, or a vote of another kind (an election by ballot).
NOT_A_VOTE = re.compile(
    r"ilman äänestystä|yksimielisesti|äänestyksettä|vaalilipuin|suljetuin lipuin|"
    r"äänestysaluejako|äänestysalue|ennakkoäänest|äänestyspaik|kuntavaal|vaalilautakun|"
    r"äänestyslipp|vaalitoimit|äänioikeu",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def vote_sentences(item: dict) -> list[str]:
    out = []
    for s in item.get("sections", []):
        if s["type"] not in ("deliberation", "decision"):
            continue
        for sent in _sentences(s["text"]):
            if VOTE_TEXT.search(sent) and not NOT_A_VOTE.search(sent):
                out.append(sent)
    return out


def audit(city: str, samples: int) -> dict:
    root = Path("data") / city / "meetings"
    c: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    missing: list[tuple[str, list[str], list[str]]] = []
    for path in sorted(root.glob("*/*.json")):
        mf = json.loads(path.read_text(encoding="utf-8"))
        if mf["meeting"]["stage"] != "minutes":
            continue
        for it in mf["items"]:
            if it.get("status") == "tombstone":
                continue
            c["items"] += 1
            votes = it.get("votes", [])
            c["votes"] += len(votes)
            c["ballots"] += sum(len(v.get("ballots", [])) for v in votes)
            c["votes_with_ballots"] += sum(1 for v in votes if v.get("ballots"))
            for v in votes:
                if v.get("needs_review"):
                    c["needs_review"] += 1
                    reasons[re.sub(r"\d+", "N", (v.get("review_reason") or "?"))[:90]] += 1
            sents = vote_sentences(it)
            if sents:
                c["mentions"] += 1
                if votes:
                    c["mentions_with_votes"] += 1
                else:
                    atts = [a["title"] for a in it.get("attachments", [])]
                    missing.append((it["source_url"], sents, atts))
            elif votes:
                c["votes_without_mention"] += 1
    return {"city": city, "counts": dict(c), "reasons": reasons.most_common(8), "missing": missing[:samples],
            "missing_total": len(missing)}


def main(argv: list[str]) -> None:
    samples = 8
    if argv[:1] == ["--samples"]:
        samples, argv = int(argv[1]), argv[2:]
    total: Counter[str] = Counter()
    rows = []
    for city in argv:
        r = audit(city, samples)
        rows.append(r)
        total.update(r["counts"])
    print("city | items | mention vote | of those with votes | votes | with ballots | needs_review")
    for r in rows + [{"city": "TOTAL", "counts": dict(total)}]:
        k = r["counts"]
        print(
            f"{r['city']} | {k.get('items', 0)} | {k.get('mentions', 0)} | {k.get('mentions_with_votes', 0)} | "
            f"{k.get('votes', 0)} | {k.get('votes_with_ballots', 0)} | {k.get('needs_review', 0)}"
        )
    for r in rows:
        if not r["missing"] and not r["reasons"]:
            continue
        print(f"\n=== {r['city']}: {r['missing_total']} items mention a vote without one")
        for reason, n in r["reasons"]:
            print(f"  review x{n}: {reason}")
        for url, sents, atts in r["missing"]:
            print(f"- {url}")
            for s in sents[:4]:
                print(f"    > {s[:400]}")
            if atts:
                print(f"    attachments: {' | '.join(a[:60] for a in atts[:8])}")


if __name__ == "__main__":
    main(sys.argv[1:])
