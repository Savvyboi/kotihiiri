"""Municipal finances by service class from the State Treasury (PLAN.md §19.2).

The budget report (KTAS, kunta/budget.py) splits money by type only. The financial statement report
KKTPP ("kunnan ja kuntayhtymän tilinpäätöstiedot palveluluokittain") splits each municipality's
actual income, costs and investments by service class (palveluluokka: basic education, early
childhood education, libraries, streets, ...). It comes from the same open API as the budgets: the
dataset list names each published report, its figures URL returns cells (`tunnusluku` id + `arvo`),
and the KKTPP taxonomy file names every cell.

The taxonomy's dimensions are kept as the Treasury labels them, so the site can group cells by
service class and line without this module guessing at the layout: `data/talous/palvelut/items.json`
maps each cell id to its taxonomy labels, and `data/talous/palvelut/{city}.json` holds, per year,
the non-zero value of each cell. Figures are aggregates with no personal data; notes are not kept.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import jsonio
from .budget import DATASETS_URL, FIRST_YEAR, SOURCE, TAXONOMY_URL, _amount, _json, latest_reports
from .config import DATA_DIR
from .text import collapse_ws, nfc

log = logging.getLogger(__name__)

REPORT = "KKTPP"
OUT_DIR = DATA_DIR / "talous" / "palvelut"
# Taxonomy fields that are bookkeeping, not labels of the cell.
SKIP_FIELDS = {"solutunniste"}


def parse_taxonomy(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The KKTPP taxonomy file → cell id → its labels (every scalar field the Treasury gives)."""
    cells: dict[str, dict[str, Any]] = {}
    for r in rows:
        cell = r.get("solutunniste")
        if cell is None or r.get("osakokonaisuus") == "t00":
            continue  # report metadata (business ID, period dates), not figures
        labels = {}
        for k, v in sorted(r.items()):
            if k in SKIP_FIELDS or v is None or isinstance(v, (dict, list)):
                continue
            labels[k] = collapse_ws(nfc(v)) if isinstance(v, str) else v
        cells[str(cell)] = labels
    return cells


def parse_document(rows: list[dict[str, Any]], cells: dict[str, Any]) -> dict[str, float]:
    """One report's rows → cell id → value, for known cells with a non-zero value."""
    out: dict[str, float] = {}
    for r in rows:
        cell = str(r.get("tunnusluku"))
        if cell not in cells:
            continue
        v = _amount(r.get("arvo"))
        if v:
            out[cell] = v
    return dict(sorted(out.items(), key=lambda kv: (len(kv[0]), kv[0])))


def fetch_services(client, wanted: dict[str, str], out_dir: Path = OUT_DIR) -> dict[str, int]:
    """Write data/talous/palvelut/{city}.json for each city → business ID. Returns years per city.

    A year whose report has the same approval time and URL as the stored one is kept without a fetch.
    """
    links = _json(client.get(TAXONOMY_URL))
    tax_url = next(u for u in links if u.rsplit("/", 1)[-1].upper() == f"{REPORT}.JSON")
    cells = parse_taxonomy(_json(client.get(tax_url)))
    jsonio.write(
        out_dir / "items.json", {"report": REPORT, "source": SOURCE, "taxonomy": tax_url, "cells": cells}
    )
    datasets = _json(client.get(DATASETS_URL))["aineistot"]
    reports = latest_reports(datasets, set(wanted.values()), report=REPORT)
    summary: dict[str, int] = {}
    for city, bid in sorted(wanted.items()):
        path = out_dir / f"{city}.json"
        old = {y["year"]: y for y in (jsonio.read(path)["years"] if path.exists() else [])}
        years = []
        for (b, year), rep in sorted(reports.items()):
            if b != bid or year < FIRST_YEAR:
                continue
            approved = (rep.get("hyvaksymispvm") or "")[:19]
            prev = old.get(year)
            if prev and prev.get("approved") == approved and prev.get("source_url") == rep["tunnusluvut"]:
                years.append(prev)
                continue
            try:
                rows = _json(client.get(rep["tunnusluvut"]))
            except Exception as exc:  # noqa: BLE001 - one bad report must not stop the rest
                log.warning("%s %s: %s", city, year, exc)
                if prev:
                    years.append(prev)
                continue
            years.append(
                {
                    "year": year,
                    "stage": rep.get("hyvaksymisvaihe"),
                    "approved": approved,
                    "source_url": rep["tunnusluvut"],
                    "values": parse_document(rows, cells),
                }
            )
        if not years:
            log.warning("%s (%s): no %s reports", city, bid, REPORT)
        jsonio.write(
            path,
            {
                "city": city,
                "business_id": bid,
                "report": REPORT,
                "years": sorted(years, key=lambda y: -y["year"]),
            },
        )
        summary[city] = len(years)
    return summary
