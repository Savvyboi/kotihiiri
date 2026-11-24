"""Municipal finances by service class from the State Treasury (PLAN.md §19.2).

The budget report (KTAS, kunta/budget.py) splits money by type only. The financial statement report
KKTPP ("kunnan ja kuntayhtymän tilinpäätöstiedot palveluluokittain") splits each municipality's
actual income, costs and investments by service class (palveluluokka: basic education, early
childhood education, libraries, streets, ...). It comes from the same open API as the budgets: the
dataset list names each published report, its figures URL returns cells (`tunnusluku` id + `arvo`),
and the KKTPP taxonomy file names every cell.

A KKTPP cell is one service class × one account line × one counterparty sector (about 9,000
non-zero cells a year for Helsinki). We keep what residents need: per service class, the operating
costs, the costs allocated to it from other services (vyörytykset), the operating income and the
income from allocations, each summed over the top counterparty sectors (external, internal, not
applicable) and never over their sub-sectors, which would count money twice. Net cost =
costs + allocated costs - income - allocated income, as in the Treasury's "nettokäyttökustannus".

`data/talous/palvelut/services.json` names each service class code (fi/sv/en) and
`data/talous/palvelut/{city}.json` holds, per year, code → [costs, allocated costs, income,
allocated income]; "ALL" is the municipality's total. Figures are aggregates with no personal data.
"""

from __future__ import annotations

import logging
import re
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, BinaryIO

import ijson

from . import jsonio
from .budget import DATASETS_URL, FIRST_YEAR, SOURCE, TAXONOMY_URL, _amount, _json, latest_reports
from .config import DATA_DIR
from .text import collapse_ws, nfc

log = logging.getLogger(__name__)

REPORT = "KKTPP"
OUT_DIR = DATA_DIR / "talous" / "palvelut"
# Account lines kept, in the order of the four numbers stored per service class.
LINES = {"Toimintakulut": 0, "Vyörytyskulut": 1, "Toimintatuotot": 2, "Vyörytystuotot": 3}
# Top counterparty sectors; the others are sub-sectors of "Ulkoiset" and would count twice.
SECTORS = {"Ulkoiset", "Sisäiset", "Ei soveltuva / Kaikki vastapuolet", None}
PART = "k-t08"  # operating economy by service class (k-t06 is investments)
_CODE = re.compile(r"fi_PA:x(\d+)")


def cell_key(row: dict[str, Any]) -> tuple[str, int] | None:
    """A taxonomy row → (service class code or "ALL", line index), or None for cells we skip."""
    if row.get("osakokonaisuus") != PART or row.get("sektori") not in SECTORS:
        return None
    line = LINES.get(collapse_ws(nfc(row.get("tunnusluku") or "")))
    if line is None:
        return None
    m = _CODE.search(row.get("tekstitunniste") or "")
    return (m.group(1) if m else "ALL", line)


def _name(row: dict[str, Any], lang: str) -> str:
    fi = collapse_ws(nfc(row.get("palvelu") or ""))
    v = collapse_ws(nfc(row.get(f"palvelu_{lang}") or ""))
    return v or fi


def parse_taxonomy(
    rows: Iterable[dict[str, Any]], keep: set[str] | None = None
) -> tuple[dict[str, tuple[str, int]], dict[str, dict[str, str]]]:
    """KKTPP taxonomy rows → cell id → (code, line), and code → its name in fi/sv/en.

    The taxonomy file is gigabytes (every service class × account × sector × column), so rows come
    from a stream, and `keep` limits the result to the cells some municipality actually reported.
    """
    cells: dict[str, tuple[str, int]] = {}
    names: dict[str, dict[str, str]] = {}
    for r in rows:
        cell = r.get("solutunniste")
        key = cell_key(r) if cell is not None else None
        if key is None:
            continue
        if keep is None or str(cell) in keep:
            cells[str(cell)] = key
        code = key[0]
        fi = _name(r, "fi")
        have = names.setdefault(code, {"fi": fi, "sv": fi, "en": fi})
        # Some rows of a class leave the English or Swedish name in Finnish; keep a translation.
        for lang in ("sv", "en"):
            if have[lang] == have["fi"]:
                have[lang] = _name(r, lang)
    return cells, names


def reduce_values(values: dict[str, float], cells: dict[str, tuple[str, int]]) -> dict[str, list[float]]:
    """Cell id → value → service class code → [costs, allocated costs, income, allocated income]."""
    out: dict[str, list[float]] = {}
    for cell, v in values.items():
        key = cells.get(cell)
        if key is None:
            continue
        code, line = key
        out.setdefault(code, [0.0, 0.0, 0.0, 0.0])[line] += v
    return {
        code: [round(x, 2) for x in out[code]]
        for code in sorted(out, key=lambda c: (c != "ALL", c))
        if any(round(x, 2) for x in out[code])
    }


def stream_rows(f: BinaryIO) -> Iterator[dict[str, Any]]:
    """The objects of a top-level JSON array in a file, one at a time (it may start with a BOM)."""
    if f.read(3) != b"\xef\xbb\xbf":
        f.seek(0)
    yield from ijson.items(f, "item", use_float=True)


def parse_document(rows: list[dict[str, Any]]) -> dict[str, float]:
    """One report's rows → cell id → value, for cells with a non-zero value."""
    out: dict[str, float] = {}
    for r in rows:
        if r.get("tunnusluku") is None:
            continue
        v = _amount(r.get("arvo"))
        if v:
            out[str(r["tunnusluku"])] = v
    return dict(sorted(out.items(), key=lambda kv: (len(kv[0]), kv[0])))


def fetch_services(client, wanted: dict[str, str], out_dir: Path = OUT_DIR) -> dict[str, int]:
    """Write data/talous/palvelut/{city}.json for each city → business ID. Returns years per city.

    Reports first, then the taxonomy for the cells they use. A year whose report has the same
    approval time and URL as the stored one is kept without a fetch.
    """
    datasets = _json(client.get(DATASETS_URL))["aineistot"]
    reports = latest_reports(datasets, set(wanted.values()), report=REPORT)
    files: dict[str, dict] = {}
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
                    "_raw": parse_document(rows),
                }
            )
        if not years:
            log.warning("%s (%s): no %s reports", city, bid, REPORT)
        files[city] = {
            "city": city,
            "business_id": bid,
            "report": REPORT,
            "years": sorted(years, key=lambda y: -y["year"]),
        }
    used = {cell for f in files.values() for y in f["years"] for cell in y.get("_raw", {})}
    names_path = out_dir / "services.json"
    names = jsonio.read(names_path).get("services", {}) if names_path.exists() else {}
    if used:
        links = _json(client.get(TAXONOMY_URL))
        tax_url = next(u for u in links if u.rsplit("/", 1)[-1].upper() == f"{REPORT}.JSON")
        # The file is gigabytes: download it to disk and read it as a stream.
        with tempfile.TemporaryDirectory() as tmp:
            tax_file = Path(tmp) / f"{REPORT}.json"
            size = client.download(tax_url, tax_file)
            log.info("%s taxonomy: %.0f MB", REPORT, size / 1e6)
            with tax_file.open("rb") as f:
                cells, new_names = parse_taxonomy(stream_rows(f), keep=used)
        names = {**names, **new_names}
        for f in files.values():
            for y in f["years"]:
                if "_raw" in y:
                    y["services"] = reduce_values(y.pop("_raw"), cells)
    names = dict(sorted(names.items(), key=lambda kv: (kv[0] != "ALL", kv[0])))
    jsonio.write(names_path, {"report": REPORT, "source": SOURCE, "services": names})
    for city, data in files.items():
        jsonio.write(out_dir / f"{city}.json", data)
    return {city: len(f["years"]) for city, f in files.items()}
