"""`kunta` command line (PLAN.md §11)."""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter

import typer

from . import jsonio
from .config import CACHE_DIR, DATA_DIR, ConfigError, load_cities, load_project, require_enabled
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
        validators_path=DATA_DIR / "state" / f"{city}.validators.json",
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

    try:
        with _client(city) as client:
            adapter_for(city, client).discover_bodies()
    except (ConfigError, NotImplementedError) as exc:
        _fail(str(exc))


@app.command()
def crawl(
    city: str = typer.Option(..., "--city"),
    body: str | None = typer.Option(None, "--body"),
    since: str = typer.Option("2025-01-01", "--since"),
    until: str | None = typer.Option(None, "--until"),
    window_weeks: int | None = typer.Option(None, "--window-weeks"),
    revalidate: bool = typer.Option(False, "--revalidate"),
) -> None:
    """Crawl meetings and items for one enabled city."""
    from .adapters import adapter_for

    try:
        with _client(city) as client:
            adapter = adapter_for(city, client)
            adapter.discover_bodies()
    except (ConfigError, NotImplementedError) as exc:
        _fail(str(exc))


@app.command()
def speeches(city: str = typer.Option(..., "--city"), since: str = typer.Option("2025-01-01")) -> None:
    """Fetch and parse speech transcripts (M6)."""
    _fail("speeches land in M6 (PLAN.md §15)")


@app.command()
def people(city: str = typer.Option(..., "--city")) -> None:
    """Refresh roster sources and resolve person refs (M5)."""
    _fail("people resolution lands in M5 (PLAN.md §15)")


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
        items = votes = review = 0
        for path in (DATA_DIR / cid / "meetings").glob("*/*.json"):
            mf = jsonio.read(path)
            meetings[mf["meeting"]["body_id"]] += 1
            items += len(mf["items"])
            for it in mf["items"]:
                votes += len(it.get("votes", []))
                review += sum(1 for v in it.get("votes", []) if v.get("needs_review"))
        state = "enabled" if cfg.enabled else f"disabled ({cfg.reason})"
        typer.echo(
            f"{cid}: {state} bodies={len(meetings)} meetings={sum(meetings.values())} "
            f"items={items} votes={votes} needs_review={review}"
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
