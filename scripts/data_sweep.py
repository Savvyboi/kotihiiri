"""Read-only sweep of data/{city} for data problems `kunta validate` does not flag (2026-11-26).

Run it where the data is: on a checkout for the six cities, or after the registry municipalities'
JSON has been fetched from R2 (`scripts/crawl_local.py --no-push` leaves it in data/). Prints one
section per municipality and a summary; changes nothing.

    python scripts/data_sweep.py                 # every municipality with a data/{city}/bodies.json
    python scripts/data_sweep.py raasepori nokia # only these

Checks:
- the same meeting twice: one source meeting id in two files, or two bodies of one kind meeting
  on the same day with the same item titles (a body listed under two names);
- more than one included council (council_body_id picks the first, so the others' members drop out);
- included bodies with no meetings, and councils' minutes without attendance;
- votes: ballots that disagree with counts while not marked for review, duplicate voters, reviewed
  votes without a Jaa or Ei label, placeholder labels ("Jaa"/"Ei", a bare "13.1"), the same label
  on both sides;
- mojibake (UTF-8 read as Latin-1: "Ã¤", "â€") and leftover HTML entities in any text;
- two persons with one display name, and councillors of this term without a party.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TERM_START = "2025-06-01"
MOJIBAKE = re.compile(r"Ã[\u0080-ÿ]|â€|Â[ -¿]|�|&(?:amp|nbsp|quot|lt|gt|#\d+);")
PLACEHOLDER = re.compile(r"^(?:jaa|ei|\d+(?:\.\d+)*\.?)$", re.IGNORECASE)


def strings(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from strings(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from strings(v, f"{path}[{i}]")
    elif isinstance(value, str):
        yield path, value


def sweep(city: str) -> collections.Counter:
    found: collections.Counter = collections.Counter()

    def report(kind: str, detail: str, limit: int = 12) -> None:
        found[kind] += 1
        if found[kind] <= limit:
            print(f"  {kind}: {detail}")
        elif found[kind] == limit + 1:
            print(f"  {kind}: … (more below the summary count)")

    bodies = {b["id"]: b for b in json.loads((DATA / city / "bodies.json").read_text(encoding="utf-8"))}
    included = {k: b for k, b in bodies.items() if b.get("included", True)}
    councils = [k for k, b in included.items() if b.get("kind") == "council" and "kysely" not in k]
    if len(councils) > 1:
        report("several included councils", ", ".join(councils))

    files = sorted((DATA / city / "meetings").glob("*/*.json"))
    by_source: dict[str, list[str]] = collections.defaultdict(list)
    by_day: dict[tuple[str, str], list[tuple[str, tuple[str, ...]]]] = collections.defaultdict(list)
    held: collections.Counter = collections.Counter()
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        m = doc["meeting"]
        held[m["body_id"]] += 1
        sid = (m.get("source_ids") or {}).get("meeting_id")
        if sid:
            by_source[str(sid)].append(m["id"])
        kind = bodies.get(m["body_id"], {}).get("kind", "?")
        titles = tuple(sorted((it.get("title") or "").strip().lower() for it in doc["items"]))
        by_day[(kind, m["date"])].append((m["id"], titles))
        if m["body_id"] not in bodies:
            report("meeting of a body missing from bodies.json", m["id"])
        if m["stage"] == "minutes" and not m.get("attendance") and m["body_id"] in councils:
            report("council minutes without attendance", m["id"])
        for path, text in strings(doc):
            hit = MOJIBAKE.search(text)
            if hit:
                report(
                    "mojibake or HTML entity",
                    f"{m['id']} {path}: …{text[max(0, hit.start() - 30) : hit.end() + 30]}…",
                )
        for it in doc["items"]:
            for v in it.get("votes", []):
                where = f"{it['id']} vote {v['ordinal']}"
                counts = v["counts"]
                if v.get("ballots"):
                    got = collections.Counter(b["choice"] for b in v["ballots"])
                    off = [c for c in ("jaa", "ei", "tyhja") if got.get(c, 0) != counts.get(c, 0)]
                    if off and not v.get("needs_review"):
                        report("ballots ≠ counts, not marked for review", f"{where}: {dict(got)} vs {counts}")
                    names = collections.Counter(b["person_ref"].get("raw") for b in v["ballots"])
                    for n, k in names.items():
                        if k > 1:
                            report("voter listed twice", f"{where}: {n}")
                jaa, ei = (v.get("jaa_label") or "").strip(), (v.get("ei_label") or "").strip()
                if v.get("needs_review"):
                    continue
                if not jaa or not ei:
                    report("reviewed vote without a side label", f"{where}: {jaa!r} / {ei!r}")
                elif PLACEHOLDER.match(jaa) or PLACEHOLDER.match(ei):
                    report("placeholder side label", f"{where}: {jaa!r} / {ei!r}")
                elif jaa == ei:
                    report("same label on both sides", f"{where}: {jaa[:60]!r}")

    for sid, ids in by_source.items():
        if len(ids) > 1:
            report("one source meeting in several files", f"{sid}: {', '.join(ids)}")
    for (_kind, _day), metas in by_day.items():
        seen: dict[tuple[str, ...], str] = {}
        for mid, titles in metas:
            if len(titles) >= 3 and titles in seen:
                report("same meeting under two bodies", f"{seen[titles]} = {mid}")
            seen.setdefault(titles, mid)
    for k in included:
        if not held[k]:
            report("included body with no meetings", k)

    people_path = DATA / city / "people.json"
    if people_path.exists():
        people = json.loads(people_path.read_text(encoding="utf-8"))
        names = collections.Counter(p["name"] for p in people["persons"])
        for n, k in names.items():
            if k > 1:
                report("two persons with one name", n)
        serving = {
            ms["person_id"]
            for ms in people["memberships"]
            if ms["body_id"] in councils and ms["role"] == "member" and (ms.get("end") or "9") >= TERM_START
        }
        for p in people["persons"]:
            if p["id"] in serving and not p.get("party"):
                report("councillor of this term without a party", p["name"])
    return found


def main() -> int:
    wanted = sys.argv[1:]
    cities = wanted or sorted(p.parent.name for p in DATA.glob("*/bodies.json"))
    total: collections.Counter = collections.Counter()
    for city in cities:
        if not (DATA / city / "bodies.json").exists():
            print(f"{city}: no data/{city}/bodies.json")
            continue
        print(f"== {city}")
        found = sweep(city)
        if not found:
            print("  nothing found")
        for kind, n in sorted(found.items()):
            total[f"{city}: {kind}"] = n
    print("\n== summary")
    for key, n in sorted(total.items()):
        print(f"{n:5} {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
