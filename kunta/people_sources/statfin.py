"""2025 municipal election candidates from Statistics Finland's PxWeb API (PLAN.md §8 source 4).

One table per electoral district ("Ehdokkaiden äänimäärä ja valintatieto kuntavaaleissa"); its
candidate values read "Sukunimi Etunimi / PUOLUE / Kunta". The city's table id is
`statfin_candidates_table` in config/cities.yaml. The Ministry of Justice results service has the
same data but its robots.txt refuses crawlers, so it is not used.
"""

from __future__ import annotations

import csv
import io
import json
import logging

from ..http import PoliteClient
from ..roster import PartyRow

log = logging.getLogger(__name__)

HOST = "pxdata.stat.fi"
BASE = f"https://{HOST}/PxWeb/api/v1/fi/StatFin/kvaa/"
SOURCE = "statfin-kvaa-2025"
BOM = "\ufeff"
RESULTS = {"1": "elected", "2": "deputy", "3": "not_elected"}


def parse_candidate(text: str) -> tuple[str, str, str] | None:
    """ "Sukunimi Etunimi / KOK / Espoo" → (name, party, municipality)."""
    parts = [p.strip() for p in text.split(" / ")]
    if len(parts) != 3 or not all(parts):
        return None
    return parts[0], parts[1], parts[2]


def candidate_codes(meta: dict, municipality: str) -> tuple[str, dict[str, tuple[str, str]]]:
    """The candidate variable's code and {value code: (name, party)} for one municipality."""
    var = next(v for v in meta["variables"] if v["code"].startswith("vaaliehdokas"))
    out: dict[str, tuple[str, str]] = {}
    for code, text in zip(var["values"], var["valueTexts"], strict=True):
        c = parse_candidate(text)
        if c and c[2] == municipality:
            out[code] = (c[0], c[1])
    return var["code"], out


def parse_csv(text: str, names: dict[str, tuple[str, str]]) -> list[PartyRow]:
    """CSV with an Ehdokas column (candidate text), total votes and the result code (1/2/3)."""
    by_text = {f"{n} / {p}": (n, p) for n, p in names.values()}
    reader = csv.reader(io.StringIO(text.lstrip(BOM)))
    header = next(reader, [])
    col_cand = next(i for i, h in enumerate(header) if h.startswith("Ehdokas"))
    col_votes = next(i for i, h in enumerate(header) if h.startswith("Äänimäärä"))
    col_result = next(i for i, h in enumerate(header) if h.startswith("Valintatieto"))
    rows: list[PartyRow] = []
    for rec in reader:
        if len(rec) <= max(col_cand, col_votes, col_result):
            continue
        cand = rec[col_cand].rsplit(" / ", 1)[0].strip()
        if cand not in by_text:
            continue
        name, party = by_text[cand]
        surname, _, first = name.partition(" ")
        votes = rec[col_votes].strip()
        rows.append(
            PartyRow(
                name=name,
                party=party,
                result=RESULTS.get(rec[col_result].strip(), "not_elected"),
                votes=int(votes) if votes.isdigit() else None,
                source=SOURCE,
                surname=surname,
                first=first,
            )
        )
    return rows


def fetch(client: PoliteClient, table: str, municipality: str) -> list[PartyRow]:
    url = f"{BASE}{table}.px"
    meta = json.loads(client.get(url).text)
    var_code, names = candidate_codes(meta, municipality)
    if not names:
        raise ValueError(f"{table}: no candidates for {municipality}")
    query = {
        "query": [
            {"code": var_code, "selection": {"filter": "item", "values": sorted(names)}},
            {
                "code": "contentscode",
                "selection": {"filter": "item", "values": ["kvaa-aanet_yht", "kvaa_valinta"]},
            },
        ],
        "response": {"format": "csv"},
    }
    resp = client.post_json(url, query)
    rows = parse_csv(resp.content.decode("utf-8"), names)
    log.info(
        "%s %s: %d candidates, %d elected",
        table,
        municipality,
        len(rows),
        sum(r.result == "elected" for r in rows),
    )
    return rows


def rows_from_people(people: dict) -> list[PartyRow]:
    """The candidacies already stored in a people.json, for a run where the API is unreachable."""
    rows = []
    for p in people.get("persons", []):
        e = p.get("election")
        if e:
            surname, _, first = p["sort_name"].partition(" ")
            rows.append(
                PartyRow(
                    name=p["sort_name"],
                    party=e["party"],
                    result=e["result"],
                    source=e["source"],
                    votes=e.get("votes"),
                    surname=surname,
                    first=first,
                )
            )
    return rows
