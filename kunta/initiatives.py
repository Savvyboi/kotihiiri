"""Municipal initiatives (kuntalaisaloitteet) from kuntalaisaloite.fi's Open Data API v1.

The Ministry of Justice runs the service and documents three endpoints at
https://www.kuntalaisaloite.fi/api: `/api/v1/municipalities`, `/api/v1/initiatives` (offset, limit
≤ 50, orderBy, municipality) and `/api/v1/initiatives/{id}`. The site's robots.txt disallows every
path for unnamed agents; Savvas allowed `/api/v1/` on 2026-10-18 (config/project.yaml
`robots_exceptions`, PLAN.md S16). Its Cloudflare check also answers GitHub's servers with a
challenge page, so this runs from a home connection, not from Actions.

Output, one file per municipality in our registry: `data/initiatives/{city}.json`. Author names and
author home municipalities are never stored (§2.2 rule 8), only how many authors there are;
e-mail addresses and phone numbers are stripped from titles and proposals.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

from . import jsonio
from .http import FetchFailed, PoliteClient
from .text import collapse_ws, nfc, strip_pii

log = logging.getLogger(__name__)

HOST = "www.kuntalaisaloite.fi"
API = f"https://{HOST}/api/v1"
PAGE = 50  # the API's maximum
SOURCE_URL = f"https://{HOST}/api"


class BotCheck(FetchFailed):
    """The site answered with its Cloudflare challenge page instead of data."""


@dataclass
class RunStats:
    municipalities: int = 0
    initiatives: int = 0
    details_fetched: int = 0
    details_reused: int = 0
    unmatched: list[str] = field(default_factory=list)
    stopped_early: bool = False


def api_id(uri: str | int | None) -> int | None:
    """`https://www.kuntalaisaloite.fi/api/v1/initiatives/123` → 123."""
    if uri is None:
        return None
    tail = str(uri).rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _json(client: PoliteClient, url: str) -> Any:
    resp = client.get(url)
    body = resp.content
    if resp.status in (403, 503) and (b"Just a moment" in body or b"challenge" in body):
        raise BotCheck(
            f"{url}: Cloudflare bot check (HTTP {resp.status}). Run from a home connection, not a server."
        )
    if resp.status != 200:
        raise FetchFailed(f"{url}: HTTP {resp.status}")
    return orjson.loads(body)


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    out = collapse_ws(strip_pii(nfc(text)))
    return out or None


def _count(value: Any) -> int:
    """participantCount is an integer in the list and an object with `total` in the details."""
    if isinstance(value, dict):
        return int(value.get("total") or 0)
    return int(value or 0)


def _date(value: Any) -> str | None:
    return str(value)[:10] if value else None


def normalize(entry: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any]:
    """One stored initiative from a list entry and (optionally) its details. Author names and home
    municipalities are dropped here; only counts survive."""
    url = entry.get("url") or {}
    rec: dict[str, Any] = {
        "id": api_id(entry.get("id")),
        "name": _clean(entry.get("name")) or "",
        "type": entry.get("type"),
        "collaborative": bool(entry.get("collaborative")),
        "publish_date": _date(entry.get("publishDate")),
        "sent_date": _date(entry.get("sentTime")),
        "participants": _count(entry.get("participantCount")),
        "url_fi": url.get("fi"),
        "url_sv": url.get("sv"),
    }
    if detail is not None:
        rec["proposal"] = _clean(detail.get("proposal"))
        authors = detail.get("authors") or {}
        rec["authors"] = int(authors.get("publicNames") or 0) + int(authors.get("privateNames") or 0)
        pc = detail.get("participantCount")
        if isinstance(pc, dict):
            rec["participants"] = _count(pc)
            if pc.get("externalNames"):
                rec["participants_external"] = int(pc["externalNames"])
    return {k: v for k, v in rec.items() if v is not None}


def _list_key(rec: dict[str, Any]) -> tuple:
    """Fields from the list that tell whether a stored detail is still current."""
    return (rec.get("name"), rec.get("sent_date"), rec.get("participants"), rec.get("type"))


def match_municipalities(
    api_munis: list[dict[str, Any]], ours: dict[str, str]
) -> tuple[dict[str, int], list[str]]:
    """Our city id → API municipality id, by Finnish name. Returns the map and our names with no
    match (the service lists every Finnish municipality, active in it or not)."""
    by_name = {nfc(str(m.get("nameFi", ""))).casefold(): api_id(m.get("id")) for m in api_munis}
    out: dict[str, int] = {}
    missing: list[str] = []
    for city, name in ours.items():
        mid = by_name.get(nfc(name).casefold())
        if mid is None:
            missing.append(name)
        else:
            out[city] = mid
    return out, missing


def fetch_list(client: PoliteClient, municipality: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = f"municipality={municipality}&limit={PAGE}&offset={offset}&orderBy=id"
        page = _json(client, f"{API}/initiatives?{query}")
        if not isinstance(page, list):
            raise FetchFailed(f"municipality {municipality}: list is not a JSON array")
        entries.extend(page)
        if len(page) < PAGE:
            return entries
        offset += PAGE


def municipality_file(city: str, mid: int, api_muni: dict[str, Any] | None, initiatives: list[dict]) -> dict:
    return {
        "municipality": city,
        "source": SOURCE_URL,
        "source_municipality_id": mid,
        "active_in_service": bool((api_muni or {}).get("active")),
        "initiatives": sorted(initiatives, key=lambda r: -int(r["id"])),
    }


def run(
    client: PoliteClient,
    cities: dict[str, str],
    out_dir: Path,
    *,
    details: bool = True,
    deadline: float | None = None,
) -> RunStats:
    """Fetch every initiative of the given municipalities ({city id: Finnish name}) and write
    `out_dir/{city}.json`. Details are fetched only for initiatives that are new or whose list fields
    changed since the stored file; with `deadline` (time.monotonic) the run stops cleanly and keeps
    the stored records for what it did not reach, so the next run continues."""
    stats = RunStats()
    api_munis = _json(client, f"{API}/municipalities")
    mapping, stats.unmatched = match_municipalities(api_munis, cities)
    meta = {api_id(m.get("id")): m for m in api_munis}
    for city, mid in mapping.items():
        path = out_dir / f"{city}.json"
        old = {r["id"]: r for r in (jsonio.read(path)["initiatives"] if path.exists() else [])}
        if deadline is not None and time.monotonic() > deadline:
            stats.stopped_early = True
            break
        entries = fetch_list(client, mid)
        recs: list[dict[str, Any]] = []
        for entry in entries:
            base = normalize(entry, None)
            prev = old.get(base["id"])
            if prev is not None and "proposal" in prev and _list_key(prev) == _list_key(base):
                recs.append(prev)
                stats.details_reused += 1
                continue
            out_of_time = deadline is not None and time.monotonic() > deadline
            if details and not out_of_time:
                detail = _json(client, f"{API}/initiatives/{base['id']}")
                recs.append(normalize(entry, detail))
                stats.details_fetched += 1
            else:
                stats.stopped_early = stats.stopped_early or out_of_time
                # keep what we had (with its proposal) rather than lose it; the list fields win
                recs.append({**prev, **base} if prev else base)
        jsonio.write(path, municipality_file(city, mid, meta.get(mid), recs))
        stats.municipalities += 1
        stats.initiatives += len(recs)
        log.info("%s: %d initiatives", city, len(recs))
    return stats


def load_all(out_dir: Path, cities: Iterable[str]) -> dict[str, dict]:
    return {c: jsonio.read(out_dir / f"{c}.json") for c in cities if (out_dir / f"{c}.json").exists()}
