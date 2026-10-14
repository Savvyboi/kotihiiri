"""Downloadable tables from the committed data (PLAN.md §13 /data/): one CSV and one Parquet file
per table plus `all.zip` with every CSV, written to build/exports/ (not committed).

Takedowns (config/takedowns.yaml, §2.2 rule 8) apply here as on the site: listed items are left
out with their votes, ballots and motions, and listed strings are redacted in every text field.
Output is deterministic: rows are sorted and the zip carries a fixed timestamp.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from . import jsonio
from .config import CONFIG_DIR, DATA_DIR
from .text import apply_takedown_strings

ZIP_TIME = (2025, 1, 1, 0, 0, 0)

S, N, B = pa.string(), pa.int64(), pa.bool_()
# table → [(column, arrow type)]; the order is the CSV column order
TABLES: dict[str, list[tuple[str, pa.DataType]]] = {
    "bodies": [("id", S), ("city", S), ("name_fi", S), ("kind", S), ("included", B)],
    "meetings": [
        ("id", S), ("city", S), ("body_id", S), ("date", S), ("start_time", S), ("end_time", S),
        ("location", S), ("stage", S), ("item_count", N), ("source_url", S), ("minutes_pdf_url", S),
    ],
    "items": [
        ("id", S), ("city", S), ("body_id", S), ("meeting_id", S), ("date", S), ("ordinal", N),
        ("pykala", N), ("title", S), ("case_number", S), ("decision", S), ("vote_count", N),
        ("status", S), ("source_url", S),
    ],
    "sections": [("item_id", S), ("ordinal", N), ("type", S), ("heading", S), ("text", S)],
    "votes": [
        ("id", S), ("city", S), ("body_id", S), ("item_id", S), ("date", S), ("ordinal", N),
        ("jaa_label", S), ("ei_label", S), ("jaa", N), ("ei", N), ("tyhja", N), ("poissa", N),
        ("result_text", S), ("source", S), ("needs_review", B), ("review_reason", S), ("source_url", S),
    ],
    "ballots": [
        ("vote_id", S), ("name", S), ("person_id", S), ("choice", S), ("group", S),
    ],
    "motions": [
        ("item_id", S), ("ordinal", N), ("kind", S), ("proposer", S), ("seconders", S), ("outcome", S),
        ("text", S),
    ],
    "attendance": [
        ("meeting_id", S), ("name", S), ("person_id", S), ("role", S), ("present", B), ("note", S),
    ],
    "persons": [
        ("id", S), ("city", S), ("name", S), ("sort_name", S), ("party", S), ("election_result", S),
        ("election_votes", N),
    ],
    "memberships": [
        ("person_id", S), ("body_id", S), ("role", S), ("group", S), ("start", S), ("end", S),
        ("source", S),
    ],
}  # fmt: skip

README = """Kotihiiri open data — municipal decision-making in Finnish cities.
Licence: CC BY 4.0. Credit Kotihiiri and the city the data comes from.

One CSV per table (UTF-8, comma-separated, header row); the same tables are published as Parquet.
Ids join the tables: items.meeting_id → meetings.id, votes.item_id → items.id,
ballots.vote_id → votes.id, memberships.person_id → persons.id. Names in ballots, motions and
attendance are as printed in the minutes; person_id is filled where the name is resolved.

Tables: {tables}
"""


def load_takedowns(path: Path = CONFIG_DIR / "takedowns.yaml") -> tuple[set[str], list[str]]:
    if not path.exists():
        return set(), []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return set(raw.get("items") or []), [s for s in raw.get("strings") or [] if s]


class _Rows:
    def __init__(self, strings: list[str]) -> None:
        self.strings = strings
        self.rows: dict[str, list[dict]] = {t: [] for t in TABLES}

    def add(self, table: str, **row) -> None:
        if self.strings:
            row = {
                k: apply_takedown_strings(v, self.strings) if isinstance(v, str) else v
                for k, v in row.items()
            }
        self.rows[table].append(row)


def _decision(item: dict) -> str | None:
    return next((s["text"] for s in item.get("sections", []) if s["type"] == "decision"), None)


def collect(cities: Iterable[str], data_dir: Path = DATA_DIR, takedowns=None) -> dict[str, list[dict]]:
    drop, strings = takedowns if takedowns is not None else load_takedowns()
    out = _Rows(strings)
    for city in sorted(cities):
        root = data_dir / city
        if (root / "bodies.json").exists():
            for b in jsonio.read(root / "bodies.json"):
                out.add(
                    "bodies", id=b["id"], city=city, name_fi=b["name_fi"], kind=b["kind"],
                    included=b.get("included", True),
                )  # fmt: skip
        for path in sorted((root / "meetings").glob("*/*.json")):
            mf = jsonio.read(path)
            m = mf["meeting"]
            items = [it for it in mf["items"] if it["id"] not in drop]
            out.add(
                "meetings", id=m["id"], city=city, body_id=m["body_id"], date=m["date"],
                start_time=m.get("start_time"), end_time=m.get("end_time"), location=m.get("location"),
                stage=m["stage"], item_count=len(items), source_url=m["source_url"],
                minutes_pdf_url=m.get("minutes_pdf_url"),
            )  # fmt: skip
            for a in m.get("attendance", []):
                out.add(
                    "attendance", meeting_id=m["id"], name=a["person_ref"]["raw"],
                    person_id=a["person_ref"].get("person_id"), role=a.get("role_text"),
                    present=a["present"], note=a.get("note"),
                )  # fmt: skip
            for it in items:
                _item(out, city, m, it)
        if (root / "people.json").exists():
            people = jsonio.read(root / "people.json")
            for p in people["persons"]:
                e = p.get("election") or {}
                out.add(
                    "persons", id=p["id"], city=city, name=p["name"], sort_name=p["sort_name"],
                    party=p.get("party"), election_result=e.get("result"), election_votes=e.get("votes"),
                )  # fmt: skip
            for ms in people["memberships"]:
                out.add(
                    "memberships", person_id=ms["person_id"], body_id=ms["body_id"], role=ms["role"],
                    group=ms.get("group"), start=ms.get("start"), end=ms.get("end"), source=ms["source"],
                )  # fmt: skip
    for table, rows in out.rows.items():
        # by the first column in natural order ("…/2" before "…/10"); rows that share it keep the
        # order of the source (ballots as printed, sections in document order)
        first = TABLES[table][0][0]
        rows.sort(key=lambda r: _natural(r[first]))
    return out.rows


def _natural(key: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", key))


def _item(out: _Rows, city: str, m: dict, it: dict) -> None:
    out.add(
        "items", id=it["id"], city=city, body_id=m["body_id"], meeting_id=m["id"], date=m["date"],
        ordinal=it["ordinal"], pykala=it.get("pykala"), title=it["title"], case_number=it.get("case_number"),
        decision=_decision(it), vote_count=len(it.get("votes", [])), status=it.get("status", "active"),
        source_url=it["source_url"],
    )  # fmt: skip
    for i, s in enumerate(it.get("sections", []) + it.get("statements", []), start=1):
        out.add(
            "sections", item_id=it["id"], ordinal=i, type=s["type"], heading=s.get("heading"), text=s["text"]
        )
    for i, mo in enumerate(it.get("motions", []), start=1):
        out.add(
            "motions", item_id=it["id"], ordinal=i, kind=mo["kind"], proposer=mo["proposer_ref"]["raw"],
            seconders="; ".join(r["raw"] for r in mo.get("seconder_refs", [])) or None,
            outcome=mo.get("outcome"), text=mo["text"],
        )  # fmt: skip
    for v in it.get("votes", []):
        vid = f"{it['id']}/{v['ordinal']}"
        c = v["counts"]
        out.add(
            "votes", id=vid, city=city, body_id=m["body_id"], item_id=it["id"], date=m["date"],
            ordinal=v["ordinal"], jaa_label=v["jaa_label"], ei_label=v["ei_label"], jaa=c.get("jaa", 0),
            ei=c.get("ei", 0), tyhja=c.get("tyhja", 0), poissa=c.get("poissa", 0),
            result_text=v.get("result_text"), source=v["source"], needs_review=v.get("needs_review", False),
            review_reason=v.get("review_reason"), source_url=v["source_url"],
        )  # fmt: skip
        for b in v.get("ballots", []):
            out.add(
                "ballots", vote_id=vid, name=b["person_ref"]["raw"],
                person_id=b["person_ref"].get("person_id"), choice=b["choice"], group=b.get("group_text"),
            )  # fmt: skip


def _csv(table: str, rows: list[dict]) -> bytes:
    cols = [c for c, _ in TABLES[table]]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if r.get(c) is None else r[c] for c in cols])
    return buf.getvalue().encode("utf-8")


def write(rows: dict[str, list[dict]], out_dir: Path) -> dict:
    """Write the CSV, Parquet and all.zip files; returns the manifest (also written as JSON)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"licence": "CC-BY-4.0", "tables": {}}
    csvs: dict[str, bytes] = {}
    for table, cols in TABLES.items():
        data = _csv(table, rows[table])
        csvs[table] = data
        (out_dir / f"{table}.csv").write_bytes(data)
        schema = pa.schema(cols)
        arrow = pa.Table.from_pylist([{c: r.get(c) for c, _ in cols} for r in rows[table]], schema=schema)
        pq.write_table(arrow, out_dir / f"{table}.parquet", compression="zstd")
        manifest["tables"][table] = {
            "rows": len(rows[table]),
            "columns": [c for c, _ in cols],
            "csv_bytes": len(data),
            "parquet_bytes": (out_dir / f"{table}.parquet").stat().st_size,
        }
    with zipfile.ZipFile(out_dir / "all.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("README.txt", ZIP_TIME)
        zf.writestr(info, README.format(tables=", ".join(TABLES)), zipfile.ZIP_DEFLATED)
        for table, data in csvs.items():
            zf.writestr(zipfile.ZipInfo(f"{table}.csv", ZIP_TIME), data, zipfile.ZIP_DEFLATED)
    manifest["zip_bytes"] = (out_dir / "all.zip").stat().st_size
    jsonio.write(out_dir / "manifest.json", manifest)
    return manifest
