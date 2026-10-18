"""Municipal budgets from the State Treasury's open municipal-finance API (PLAN.md §19).

Every municipality reports its approved budget and financial plan to the State Treasury
(Valtiokonttori) as the KTAS report ("Kunnan ja kuntayhtymän talousarvio ja -suunnitelma"). The
Treasury publishes the approved reports openly, without a key:

- `DATASETS_URL` lists every published report: business ID, report code, period, approval stage and
  time, and the URL of its figures;
- each figures URL returns the report's cells: a numeric cell id (`tunnusluku`) and its value;
- `TAXONOMY_URL` (the Kuntatalous API on avoindata.tutkihallintoa.fi) links one JSON file per report
  code that names every cell id in Finnish, Swedish and English, with its line, column and level.

A KTAS report for year Y has about 40 lines (operating income and expenses, tax revenue, central
government transfers, annual margin, investments, loan stock, person-years, income tax rate) in four
columns: the previous year's budget with its amendments, the budget for Y, and the plan for Y+1 and
Y+2. `fetch_budgets` writes one file per municipality, `data/talous/{city}.json`, plus the shared
line list `data/talous/items.json`. Figures are public financial data with no personal data; the
municipality's own notes (`kommentti`) still go through the PII pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import yaml

from . import jsonio
from .config import CONFIG_DIR, DATA_DIR
from .ids import slugify
from .text import collapse_ws, nfc, strip_pii

log = logging.getLogger(__name__)

DATASETS_URL = "https://prodkuntarest.westeurope.cloudapp.azure.com/rest/v1/json/aineistot"
TAXONOMY_URL = "https://api.tutkihallintoa.fi/kuntatalous/v1/taksonomia"
HOSTS = {
    "prodkuntarest.westeurope.cloudapp.azure.com",
    "api.tutkihallintoa.fi",
    "tkdpprodjrpstacc02.blob.core.windows.net",
}
REPORT = "KTAS"
FIRST_YEAR = 2020
SOURCE = {
    "name": "Valtiokonttori, Kuntien ja hyvinvointialueiden taloustietopalvelu",
    "url": "https://www.tutkihallintoa.fi/kuntien-ja-kuntayhtymien-talous/",
    "licence": "CC BY 4.0",
}
# Taxonomy column (`tehtava`, by its order) → our column key.
COLUMNS = {1: "prev", 2: "budget", 3: "plan1", 4: "plan2"}
# A later stage replaces an earlier one for the same report.
STAGES = {"Alustava": 0, "Lopullinen": 1, "Jälkikorjattu": 2}
OUT_DIR = DATA_DIR / "talous"


@dataclass(frozen=True)
class Cell:
    key: str
    column: str


@dataclass(frozen=True)
class Line:
    key: str
    order: int
    level: int
    fi: str
    sv: str
    en: str


def load_business_ids(config_dir: Path = CONFIG_DIR) -> dict[str, str]:
    """Municipality id → business ID, from config/registry/business_ids.yaml."""
    raw = yaml.safe_load((config_dir / "registry" / "business_ids.yaml").read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in (raw or {}).items() if v}


def parse_taxonomy(rows: list[dict[str, Any]]) -> tuple[list[Line], dict[str, Cell]]:
    """The KTAS taxonomy file → budget lines in report order and cell id → (line, column)."""
    lines: dict[str, Line] = {}
    cells: dict[str, Cell] = {}
    for r in rows:
        if r.get("osakokonaisuus") == "t00" or not r.get("tunnusluku"):
            continue  # report metadata (business ID, period dates), not figures
        column = COLUMNS.get(r.get("tehtava_jarjestys") or 0)
        if column is None:
            continue
        fi = collapse_ws(nfc(r["tunnusluku"]))
        key = slugify(fi)
        line = Line(
            key=key,
            order=int(r.get("tunnusluku_jarjestys") or 0),
            level=int(r.get("taso") or 1),
            fi=fi,
            sv=collapse_ws(nfc(r.get("tunnusluku_sv") or fi)),
            en=collapse_ws(nfc(r.get("tunnusluku_en") or fi)),
        )
        if key in lines:
            have = lines[key]
            if have.order != line.order:
                raise ValueError(f"two KTAS lines share the key {key!r}")
            # Every column repeats the labels; keep a translation wherever one column has it.
            line = Line(
                key,
                have.order,
                have.level,
                fi,
                have.sv if have.sv != fi else line.sv,
                have.en if have.en != fi else line.en,
            )
        lines[key] = line
        cells[str(r["solutunniste"])] = Cell(key, column)
    return sorted(lines.values(), key=lambda x: x.order), cells


def latest_reports(datasets: list[dict[str, Any]], business_ids: set[str]) -> dict[tuple[str, int], dict]:
    """(business ID, year) → the newest published KTAS report of that year."""
    best: dict[tuple[str, int], dict] = {}
    for r in datasets:
        if r.get("raportointikokonaisuus") != REPORT or r.get("ytunnus") not in business_ids:
            continue
        period = str(r.get("raportointikausi", ""))
        if not period.isdigit() or int(period) < FIRST_YEAR:
            continue
        k = (r["ytunnus"], int(period))
        rank = (STAGES.get(r.get("hyvaksymisvaihe"), -1), r.get("hyvaksymispvm") or "")
        if k not in best or rank > best[k]["_rank"]:
            best[k] = {**r, "_rank": rank}
    return best


def _amount(text: Any) -> float | None:
    try:
        return round(float(str(text).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return None


def parse_document(rows: list[dict[str, Any]], cells: dict[str, Cell]) -> tuple[dict, dict]:
    """One report's cells → {line: {column: value}} and {line: note}."""
    values: dict[str, dict[str, float]] = {}
    notes: dict[str, str] = {}
    for r in rows:
        cell = cells.get(str(r.get("tunnusluku")))
        if cell is None:
            continue
        v = _amount(r.get("arvo"))
        if v is not None:
            values.setdefault(cell.key, {})[cell.column] = v
        note = collapse_ws(strip_pii(nfc(r.get("kommentti") or ""))).replace("??", " ").strip()
        if note and cell.column == "budget":
            notes[cell.key] = note
    return values, notes


def year_entry(report: dict, rows: list[dict[str, Any]], cells: dict[str, Cell]) -> dict:
    values, notes = parse_document(rows, cells)
    entry = {
        "year": int(report["raportointikausi"]),
        "stage": report.get("hyvaksymisvaihe"),
        "approved": (report.get("hyvaksymispvm") or "")[:19],
        "source_url": report["tunnusluvut"],
        "values": values,
    }
    if notes:
        entry["notes"] = notes
    return entry


def _json(resp) -> Any:
    return orjson.loads(resp.content.decode("utf-8-sig"))


def fetch_budgets(
    client, cities: list[str], out_dir: Path = OUT_DIR, business_ids: dict[str, str] | None = None
) -> dict:
    """Write data/talous/{city}.json for each city with a business ID. Returns per-city counts.

    A year whose report has the same approval time as the stored one is kept without a fetch.
    """
    ids = business_ids if business_ids is not None else load_business_ids()
    wanted = {c: ids[c] for c in cities if c in ids}
    links = _json(client.get(TAXONOMY_URL))
    tax_url = next(u for u in links if u.rsplit("/", 1)[-1].upper() == f"{REPORT}.JSON")
    lines, cells = parse_taxonomy(_json(client.get(tax_url)))
    jsonio.write(
        out_dir / "items.json",
        {
            "report": REPORT,
            "source": SOURCE,
            "lines": [line.__dict__ for line in lines],
        },
    )
    datasets = _json(client.get(DATASETS_URL))["aineistot"]
    reports = latest_reports(datasets, set(wanted.values()))
    summary: dict[str, int] = {}
    for city, bid in sorted(wanted.items()):
        path = out_dir / f"{city}.json"
        old = {y["year"]: y for y in (jsonio.read(path)["years"] if path.exists() else [])}
        years = []
        for (b, year), rep in sorted(reports.items()):
            if b != bid:
                continue
            prev = old.get(year)
            if (
                prev
                and prev.get("approved") == (rep.get("hyvaksymispvm") or "")[:19]
                and prev.get("source_url") == rep["tunnusluvut"]
            ):
                years.append(prev)
                continue
            try:
                rows = _json(client.get(rep["tunnusluvut"]))
            except Exception as exc:  # noqa: BLE001 - one bad report must not stop the rest
                log.warning("%s %s: %s", city, year, exc)
                if prev:
                    years.append(prev)
                continue
            years.append(year_entry(rep, rows, cells))
        if not years:
            log.warning("%s (%s): no %s reports", city, bid, REPORT)
        jsonio.write(
            path,
            {
                "city": city,
                "business_id": bid,
                "report": REPORT,
                "source": SOURCE,
                "years": sorted(years, key=lambda y: -y["year"]),
            },
        )
        summary[city] = len(years)
    return summary
