"""`kunta` command line (PLAN.md §11)."""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter
from pathlib import Path

import typer

from . import jsonio
from .config import CACHE_DIR, DATA_DIR, ROOT, ConfigError, load_cities, load_project, require_enabled
from .text import is_confidential
from .validate import validate_city

app = typer.Typer(no_args_is_help=True, help="Finnish city decisions scraper. See PLAN.md.")
log = logging.getLogger("kunta")


def _client(city: str):
    from .http import PoliteClient

    cfg = require_enabled(city)
    project = load_project()
    hosts = {u.split("://", 1)[1].split("/", 1)[0] for u in cfg.base_urls}
    return PoliteClient(
        project.user_agent,
        cache_dir=CACHE_DIR,
        # ETags only help together with the cached bodies, so they live next to them, not in data/.
        validators_path=CACHE_DIR.parent / "validators" / f"{city}.json",
        allowed_hosts=hosts,
    )


def _fail(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )


@app.command()
def discover(city: str = typer.Option(..., "--city")) -> None:
    """Update config/bodies/CITY.yaml with discovered bodies (keeps manual flags)."""
    from .adapters import adapter_for
    from .crawl import write_bodies

    try:
        with _client(city) as client:
            bodies = adapter_for(city, client).discover_bodies()
    except (ConfigError, NotImplementedError) as exc:
        _fail(str(exc))
    write_bodies(city, bodies)
    included = sum(b.included for b in bodies)
    typer.echo(f"{city}: {len(bodies)} bodies discovered, {included} included")


@app.command()
def crawl(
    city: str = typer.Option(..., "--city"),
    body: str | None = typer.Option(None, "--body"),
    since: str = typer.Option("2025-01-01", "--since"),
    until: str | None = typer.Option(None, "--until"),
    window_weeks: int | None = typer.Option(None, "--window-weeks"),
    revalidate: bool = typer.Option(False, "--revalidate"),
    max_minutes: float | None = typer.Option(
        None, "--max-minutes", help="stop cleanly after this long so the workflow can still commit"
    ),
) -> None:
    """Crawl meetings and items for one enabled city."""
    from .adapters import adapter_for
    from .crawl import crawl as run_crawl

    try:
        with _client(city) as client:
            report = run_crawl(
                adapter_for(city, client),
                city,
                since=dt.date.fromisoformat(since),
                until=dt.date.fromisoformat(until) if until else None,
                body_filter=body,
                window_weeks=window_weeks,
                revalidate=revalidate,
                max_seconds=max_minutes * 60 if max_minutes else None,
            )
            http = client.stats
    except (ConfigError, NotImplementedError) as exc:
        _fail(str(exc))
    typer.echo(report.summary())
    typer.echo(
        f"http: requests={http.requests} not_modified={http.not_modified} "
        f"skipped_robots={len(http.skipped_robots)} failures={len(http.failures)}"
    )
    for url in report.needs_refetch:
        typer.echo(f"  needs_refetch: {url}")
    if report.alarms:
        for a in report.alarms:
            typer.secho(f"  LAYOUT ALARM: {a}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)


@app.command()
def speeches(
    city: str = typer.Option(..., "--city"),
    since: str = typer.Option("2025-01-01", "--since"),
    refresh: bool = typer.Option(False, "--refresh", help="re-parse transcripts already stored"),
) -> None:
    """Write data/{city}/speeches/ from the council's speech transcripts (M6; Helsinki only)."""
    from .speeches import run

    try:
        with _client(city) as client:
            report = run(city, client, since=since, refresh=refresh)
    except (ConfigError, NotImplementedError) as exc:
        _fail(str(exc))
    typer.echo(report.summary())
    for name, n in sorted(report.unresolved.items(), key=lambda kv: (-kv[1], kv[0])):
        typer.echo(f"  unresolved speaker: {name} ({n})")
    for f in report.failures:
        typer.echo(f"  failed: {f}")


@app.command()
def people(city: str = typer.Option(..., "--city")) -> None:
    """Write data/{city}/people.json: persons and memberships from attendance lists and Helsinki's
    vote tables, with party and result from the 2025 election (PLAN.md §8)."""
    from .http import FetchFailed
    from .people import name_key
    from .people_sources import statfin
    from .roster import PartyRow, build, council_body_id, load_overrides

    try:
        cfg = require_enabled(city)
        ua = load_project().user_agent
    except ConfigError as exc:
        _fail(str(exc))
    out = DATA_DIR / city / "people.json"
    roster = build(city, council_body_id(city))
    rows: list[PartyRow] = []
    table = cfg.extra.get("statfin_candidates_table")
    if table:
        from .http import PoliteClient

        try:
            with PoliteClient(ua, allowed_hosts={statfin.HOST}) as client:
                rows = statfin.fetch(client, str(table), cfg.name_fi)
        except (FetchFailed, ValueError, KeyError) as exc:
            # Keep last week's parties rather than dropping them when Statistics Finland is down.
            log.warning("statfin unavailable (%s); reusing the parties in %s", exc, out)
            rows = statfin.rows_from_people(jsonio.read(out)) if out.exists() else []
    matched, missing = roster.add_parties(rows, load_overrides(city) if rows else None)
    changed = jsonio.write(out, roster.to_json())
    elected = sum(r.result == "elected" for r in rows)
    found = len(
        {id(p.election) for p in roster.people.values() if p.election and p.election.result == "elected"}
    )
    typer.echo(
        f"{city}: persons={len(roster.people)} with_party={matched} "
        f"elected_found={found}/{elected} changed={changed}"
    )
    if missing:
        typer.echo(f"  council members without a party ({len(missing)}): {', '.join(missing)}")
        # Candidates sharing a name with each, to write overrides from (§8 source 5).
        for name in missing:
            mine = {t for t in name_key(name).split() if len(t) > 2}
            near = [f"{r.name} ({r.party}, {r.result})" for r in rows if mine & set(name_key(r.name).split())]
            typer.echo(f"    {name}: {'; '.join(near[:8]) or '-'}")
    taken = {id(p.election) for p in roster.people.values() if p.election}
    unmatched = [f"{r.name} ({r.party})" for r in rows if r.result == "elected" and id(r) not in taken]
    if unmatched:
        typer.echo(f"  elected candidates not on any roster ({len(unmatched)}): {', '.join(unmatched)}")


@app.command()
def validate(city: str | None = typer.Option(None, "--city")) -> None:
    """Validate committed data. Exits non-zero if any city has errors."""
    cities = [city] if city else list(load_cities())
    failed = False
    for c in cities:
        r = validate_city(c)
        status = "ok" if r.ok else "FAIL"
        typer.echo(f"{c}: {status} files={r.files} errors={len(r.errors)} warnings={len(r.warnings)}")
        for e in r.errors:
            typer.echo(f"  error: {e}")
        for w in r.warnings:
            typer.echo(f"  warning: {w}")
        failed |= not r.ok
    if failed:
        raise typer.Exit(1)


@app.command()
def export(out: str | None = typer.Option(None, "--out", help="default build/exports")) -> None:
    """Write one CSV and one Parquet file per table plus all.zip and manifest.json (PLAN.md §13
    /data/), from the committed data of the enabled cities, with takedowns applied."""
    from .export import collect, write

    cities = [c for c, cfg in load_cities().items() if cfg.enabled and (DATA_DIR / c).exists()]
    out_dir = Path(out) if out else ROOT / "build" / "exports"
    manifest = write(collect(cities), out_dir)
    for table, t in manifest["tables"].items():
        typer.echo(f"{table}: rows={t['rows']} csv={t['csv_bytes']} parquet={t['parquet_bytes']}")
    typer.echo(f"all.zip: {manifest['zip_bytes']} bytes in {out_dir}")


@app.command()
def stats() -> None:
    """Counts per city/body."""
    for cid, cfg in load_cities().items():
        meetings: Counter[str] = Counter()
        items = votes = review = minutes_items = with_decision = 0
        for path in (DATA_DIR / cid / "meetings").glob("*/*.json"):
            mf = jsonio.read(path)
            meetings[mf["meeting"]["body_id"]] += 1
            items += len(mf["items"])
            for it in mf["items"]:
                if (
                    mf["meeting"]["stage"] == "minutes"
                    and it.get("status") != "tombstone"
                    and not is_confidential(it["title"])  # no public decision exists
                ):
                    minutes_items += 1
                    with_decision += any(s["type"] == "decision" for s in it.get("sections", []))
                votes += len(it.get("votes", []))
                review += sum(1 for v in it.get("votes", []) if v.get("needs_review"))
        state = "enabled" if cfg.enabled else f"disabled ({cfg.reason})"
        typer.echo(
            f"{cid}: {state} bodies={len(meetings)} meetings={sum(meetings.values())} "
            f"items={items} votes={votes} needs_review={review}"
            + (f" decision_coverage={with_decision / minutes_items:.1%}" if minutes_items else "")
        )


@app.command()
def registry(
    check: bool = typer.Option(False, "--check", help="fail if the committed file is stale"),
) -> None:
    """Write config/municipalities.yaml from cities.yaml, the registry CSV, the robots audit and
    config/registry/rollout.yaml (PLAN.md §18.1, M10)."""
    from . import registry as reg

    if check:
        if reg.is_stale():
            _fail("config/municipalities.yaml is stale; run `kunta registry`")
        typer.echo("config/municipalities.yaml is up to date")
        return
    changed = reg.write()
    m = reg.build()
    enabled = sum(1 for v in m.values() if v.get("enabled"))
    reasons = Counter(v.get("reason") for v in m.values() if not v.get("enabled"))
    typer.echo(f"{len(m)} municipalities, {enabled} enabled, changed={changed}")
    for reason, n in sorted(reasons.items()):
        typer.echo(f"  {reason}: {n}")


@app.command()
def groups(
    cities: str = typer.Option("all", "--cities", help="comma-separated slugs, or `all` enabled"),
) -> None:
    """Print the weekly crawl matrix as JSON (PLAN.md §18.2)."""
    import json

    from .registry import crawl_groups

    selected = None if cities.strip() in ("", "all") else [c.strip() for c in cities.split(",") if c.strip()]
    typer.echo(json.dumps(crawl_groups(selected)))


@app.command()
def audit(
    only: str | None = typer.Option(None, "--only", help="comma-separated municipality slugs"),
    since: str = typer.Option("2025-01-01", "--since"),
    no_counts: bool = typer.Option(False, "--no-counts", help="robots.txt only"),
) -> None:
    """Robots audit of every registry host, plus council/board meeting counts from listing pages
    (PLAN.md M10). Writes data/state/robots.json and data/state/audit.json."""
    from . import audit as au

    try:
        ua = load_project().user_agent
    except ConfigError as exc:
        _fail(str(exc))
    hosts, report = au.run(
        ua,
        dt.date.fromisoformat(since),
        only={s.strip() for s in only.split(",")} if only else None,
        counts=not no_counts,
    )
    au.write(hosts, report, dt.date.today(), dt.date.fromisoformat(since))
    for host, r in sorted(hosts.items()):
        blocked = f" blocked={','.join(r.get('blocked', []))}" if r.get("blocked") else ""
        typer.echo(f"{host}: {r['status']} (robots {r['robots']}){blocked}")
    for slug, r in report.items():
        meetings = r.get("meetings", {})
        counts = " ".join(f"{b}={m.get('meetings', 'ERR')}" for b, m in meetings.items())
        line = f"{slug}: {counts}"
        if r.get("error"):
            line += f" ERROR {r['error']}"
        for p in r.get("problems", []):
            line += f" | {p}"
        typer.echo(line)


@app.command()
def initiatives(
    cities: str = typer.Option("all", "--cities", help="comma-separated slugs, or `all` in the registry"),
    details: bool = typer.Option(True, "--details/--no-details", help="fetch each new or changed initiative"),
    max_minutes: float | None = typer.Option(None, "--max-minutes", help="stop cleanly after this long"),
) -> None:
    """Municipal initiatives from kuntalaisaloite.fi's Open Data API → data/initiatives/{city}.json.

    Run from a home connection: the site's bot check refuses GitHub's servers (PLAN.md S16)."""
    import time

    from .http import PoliteClient
    from .initiatives import HOST, BotCheck, run

    every = load_cities()
    wanted = list(every) if cities == "all" else [c.strip() for c in cities.split(",") if c.strip()]
    unknown = [c for c in wanted if c not in every]
    if unknown:
        _fail(f"unknown municipalities: {', '.join(unknown)}")
    project = load_project()
    if HOST not in project.robots_exceptions:
        _fail(f"{HOST}'s robots.txt disallows us and config/project.yaml has no robots_exceptions entry")
    deadline = time.monotonic() + max_minutes * 60 if max_minutes else None
    with PoliteClient(
        project.user_agent, allowed_hosts={HOST}, robots_exceptions=project.robots_exceptions
    ) as client:
        try:
            stats = run(
                client,
                {c: every[c].name_fi for c in wanted},
                DATA_DIR / "initiatives",
                details=details,
                deadline=deadline,
            )
        except BotCheck as exc:
            _fail(str(exc))
    typer.echo(
        f"{stats.municipalities} municipalities, {stats.initiatives} initiatives, "
        f"{stats.details_fetched} details fetched, {stats.details_reused} reused, "
        f"{client.stats.requests} requests"
    )
    if stats.unmatched:
        typer.echo(f"not in the service: {', '.join(stats.unmatched)}")
    if stats.stopped_early:
        typer.echo("stopped at --max-minutes; run again to continue")


@app.command()
def heartbeat() -> None:
    """Write data/state/heartbeat.json so scheduled workflows always commit (PLAN.md §2.3)."""
    jsonio.write(
        DATA_DIR / "state" / "heartbeat.json",
        {"last_run": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()},
    )


if __name__ == "__main__":
    app()
