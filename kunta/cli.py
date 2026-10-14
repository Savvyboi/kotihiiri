"""`kunta` command line (PLAN.md §11)."""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter

import typer

from . import jsonio
from .config import CACHE_DIR, DATA_DIR, ConfigError, load_cities, load_project, require_enabled
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
def speeches(city: str = typer.Option(..., "--city"), since: str = typer.Option("2025-01-01")) -> None:
    """Fetch and parse speech transcripts (M6)."""
    _fail("speeches land in M6 (PLAN.md §15)")


@app.command()
def people(city: str = typer.Option(..., "--city")) -> None:
    """Write data/{city}/people.json: persons and memberships from attendance lists and Helsinki's
    vote tables, with party and result from the 2025 election (PLAN.md §8)."""
    from .http import FetchFailed
    from .people_sources import statfin
    from .roster import PartyRow, build, council_body_id

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
    matched, missing = roster.add_parties(rows)
    changed = jsonio.write(out, roster.to_json())
    typer.echo(f"{city}: persons={len(roster.people)} with_party={matched} changed={changed}")
    if missing:
        typer.echo(f"  council members without a party ({len(missing)}): {', '.join(missing)}")


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
def export() -> None:
    """Write build/exports/*.parquet, *.csv, all.zip (M7)."""
    _fail("exports land in M7 (PLAN.md §15)")


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
def heartbeat() -> None:
    """Write data/state/heartbeat.json so scheduled workflows always commit (PLAN.md §2.3)."""
    jsonio.write(
        DATA_DIR / "state" / "heartbeat.json",
        {"last_run": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()},
    )


if __name__ == "__main__":
    app()
