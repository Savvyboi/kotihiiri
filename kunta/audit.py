"""Robots and listing audit of every registry host (PLAN.md M10, S11, S13).

For each host: fetch robots.txt with our User-Agent and test the paths its adapter needs. For each
municipality from the registry whose hosts allow those paths: discover bodies and count council and
board meetings since `since` from the listing pages only (no meeting or item pages). Oulu and Turku
are only checked for robots.txt; nothing else is fetched from them (§2.1 rule 2).

Writes `data/state/robots.json` (per host) and `data/state/audit.json` (per municipality).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlsplit

from .adapters import ADAPTERS
from .bodies import default_included, guess_kind
from .config import DATA_DIR, CityConfig, load_cities
from .http import FetchFailed, PoliteClient, RobotsDisallowed
from .models import BodyKind

log = logging.getLogger(__name__)

# Paths each adapter fetches, with placeholder ids: robots rules match on path shape.
ADAPTER_PATHS = {
    "dynasty": [
        "/cgi/DREQUEST.PHP?page=meeting_frames",
        "/cgi/DREQUEST.PHP?page=meetings&id=1",
        "/cgi/DREQUEST.PHP?page=meeting&id=20251",
        "/cgi/DREQUEST.PHP?page=meetingitem&id=20251-1",
        "/kokous/20251.PDF",
        "/kokous/20251-1-1.PDF",
    ],
    "casem": [
        "/fi-FI/Toimielimet",
        "/fi-FI/Toimielimet/Kaupunginvaltuusto",
        "/fi-FI/Toimielimet/Kaupunginvaltuusto/Kokous_1012025",
        "/fi-FI/content/1/1",
        "/download/noname/{00000000-0000-0000-0000-000000000000}/1",
    ],
    "tweb": [
        "/ktwebscr/pk_tek_tweb.htm",
        "/ktwebscr/epj_tek_tweb.htm",
        "/ktwebbin/dbisa.dll/ktwebscr/pk_kokl_tweb.htm?+kirjaamo=1",
        "/ktwebscr/epj_kokl_tweb.htm?+kirjaamo=1",
        "/ktwebscr/pk_asil_tweb.htm?+bid=1",
        "/ktwebbin/dbisa.dll/ktwebscr/fileshow?doctype=3&docid=1",
        "/ktwebscr/fileshow?doctype=3&docid=1",
    ],
    "helsinki": ["/fi/paattajat/kaupunginvaltuusto", "/fi/asia/hel-2025-000001"],
    "turku": ["/"],
}


@dataclass
class HostResult:
    status: str  # allowed | partial | disallowed | no_robots | unreachable
    robots: str  # how robots.txt answered: ok | no_robots | forbidden | unreachable
    blocked: list[str]

    def to_json(self) -> dict:
        out: dict = {"status": self.status, "robots": self.robots}
        if self.blocked:
            out["blocked"] = self.blocked
        return out


def _paths(cfg: CityConfig, base: str) -> list[str]:
    prefix = urlsplit(base).path.rstrip("/")
    paths = ADAPTER_PATHS.get(cfg.adapter, ["/"])
    if cfg.adapter == "tweb" and cfg.extra.get("tweb_dll_paths"):
        paths = paths + [p.replace("/ktwebscr/", "/ktwebbin/dbisa.dll/ktwebscr/") for p in paths]
    return [prefix + p for p in paths]


def check_host(client: PoliteClient, cfg: CityConfig, base: str) -> HostResult:
    parts = urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    urls = [origin + p for p in _paths(cfg, base)]
    verdicts = {u: client.allowed(u) for u in urls}
    robots = client.robots_status.get(parts.netloc, "unreachable")
    blocked = sorted(
        urlsplit(u).path + (f"?{urlsplit(u).query}" if urlsplit(u).query else "")
        for u, ok in verdicts.items()
        if not ok
    )
    if robots == "unreachable":
        status = "unreachable"
    elif robots == "forbidden" or len(blocked) == len(urls):
        status = "disallowed"
    elif blocked:
        status = "partial"
    else:
        status = "no_robots" if robots == "no_robots" else "allowed"
    return HostResult(status, robots, blocked)


def count_listings(client: PoliteClient, slug: str, cfg: CityConfig, since: dt.date) -> dict:
    """Bodies and council/board meeting counts from listing pages only."""
    adapter = ADAPTERS[cfg.adapter](client, cfg.base_urls[0])
    adapter.city = slug
    out: dict = {}
    try:
        bodies = adapter.discover_bodies()
    except (FetchFailed, RobotsDisallowed, Exception) as exc:  # noqa: BLE001 — record any parser failure
        return {"error": f"bodies: {type(exc).__name__}: {exc}"[:300]}
    out["bodies_total"] = len(bodies)
    kept = [b for b in bodies if default_included(b.name_fi, slug)]
    out["bodies"] = {
        b.id.split("/", 1)[1]: {"name": b.name_fi, "kind": str(guess_kind(b.name_fi)), **b.source_ids}
        for b in kept
    }
    kinds = Counter(str(guess_kind(b.name_fi)) for b in kept)
    problems = []
    if kinds[BodyKind.council] != 1:
        problems.append(f"{kinds[BodyKind.council]} council bodies")
    if kinds[BodyKind.board] != 1:
        problems.append(f"{kinds[BodyKind.board]} board bodies")
    expected = cfg.extra.get("council_source_id")
    if expected:
        found = {v for b in kept if guess_kind(b.name_fi) == BodyKind.council for v in b.source_ids.values()}
        if found and str(expected) not in found:
            problems.append(f"council id {expected} from the registry not among {sorted(found)}")
    meetings: dict[str, dict] = {}
    for b in kept:
        try:
            refs = adapter.list_meetings(b, since, None)
        except Exception as exc:  # noqa: BLE001
            meetings[b.id.split("/", 1)[1]] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
            continue
        stages = Counter(str(r.stage) for r in refs)
        meetings[b.id.split("/", 1)[1]] = {
            "meetings": len(refs),
            "stages": dict(sorted(stages.items())),
            "latest": max((r.date.isoformat() for r in refs), default=None),
        }
        if not refs:
            problems.append(f"no meetings since {since} for {b.name_fi}")
    out["meetings"] = meetings
    if problems:
        out["problems"] = problems
    return out


def run(
    user_agent: str, since: dt.date, only: set[str] | None = None, counts: bool = True
) -> tuple[dict, dict]:
    cities = load_cities()
    hosts: dict[str, dict] = {}
    report: dict[str, dict] = {}
    client = PoliteClient(user_agent)
    try:
        for slug, cfg in cities.items():
            if only and slug not in only:
                continue
            entry: dict = {"adapter": cfg.adapter}
            if not cfg.base_urls:
                entry["skipped"] = "no source system in the registry"
                report[slug] = entry
                continue
            results = {}
            for base in cfg.base_urls:
                host = urlsplit(base).netloc
                res = check_host(client, cfg, base)
                shared = hosts.get(host, {}).get("municipalities", [])
                hosts[host] = {**res.to_json(), "municipalities": sorted({slug, *shared})}
                results[host] = res.status
            entry["hosts"] = results
            from_registry = int(cfg.extra.get("rank", 0)) > 6
            ok = all(s in ("allowed", "no_robots") for s in results.values())
            if counts and from_registry and ok and cfg.adapter in ("dynasty", "casem", "tweb"):
                log.info("listing %s", slug)
                entry.update(count_listings(client, slug, cfg, since))
            report[slug] = entry
    finally:
        client.close()
    return hosts, report


def write(hosts: dict, report: dict, checked: dt.date, since: dt.date, merge: bool = True) -> None:
    from . import jsonio

    robots_path = DATA_DIR / "state" / "robots.json"
    audit_path = DATA_DIR / "state" / "audit.json"
    old_hosts = jsonio.read(robots_path).get("hosts", {}) if merge and robots_path.exists() else {}
    old_report = jsonio.read(audit_path).get("municipalities", {}) if merge and audit_path.exists() else {}
    stamped = {h: {**v, "checked": checked.isoformat()} for h, v in hosts.items()}
    jsonio.write(robots_path, {"hosts": dict(sorted({**old_hosts, **stamped}.items()))})
    merged = {**old_report, **report}
    order = list(load_cities())
    ordered = {
        s: merged[s] for s in sorted(merged, key=lambda s: order.index(s) if s in order else len(order))
    }
    jsonio.write(audit_path, {"since": since.isoformat(), "municipalities": ordered})
