"""Weekly crawl of the `crawl_from: local` municipalities from a home connection (PLAN.md §7.6, M14).

Their hosts do not answer GitHub's servers (Turku since the M10 audit; the 13 *.tweb.fi hosts, the
4 *.triplancloud.fi hosts, Ylivieska and Nivala since the 2026-11-15 robots-override crawl), so this
does on Savvas's computer what the weekly workflow's crawl and commit jobs do. Same polite client,
same robots-override limits (one request per 5 s per host, stop a host on its first refusal), same
User-Agent. For each municipality: crawl, roster, validate, then

- six-city municipalities (Turku): commit data/{city}, its crawl state and body config, and push;
- registry municipalities: fetch last week's JSON and crawl state from R2 first, sync them back to
  R2 afterwards (as weekly.yml does), and commit only the body config.

A municipality whose crawl raised a layout alarm or failed validation is left out of the upload and
the commit; the others still go through. All municipalities share one time budget (`--max-minutes`),
and one that does not fit continues next run. The site picks the data up on the next deploy.

    python scripts/crawl_local.py                      # weekly: every crawl_from: local municipality
    python scripts/crawl_local.py turku nokia          # only these
    python scripts/crawl_local.py --window all         # first run / full refresh
    python scripts/crawl_local.py --no-push            # crawl and validate only; no R2, no git
    python scripts/crawl_local.py --briefs-only        # no crawl: AI briefs of new meetings, then push

AI briefs (PLAN.md §20): when OPENROUTER_API_KEY is set, every run ends with `kunta briefs` for the
six cities and the registry municipalities crawled here, at most `--briefs-requests` requests (700,
Savvas's daily allowance; four requests run at once, so 700 take a few hours). Briefs of the six
cities are committed with the data; those of registry municipalities go to R2 next to their
meetings. Without the key the step is skipped.

Registry municipalities need rclone with an `r2` remote for the kotihiiri-data bucket, e.g. the same
RCLONE_CONFIG_R2_* environment variables weekly.yml sets (PLAN.md §18.4), or `rclone config`.

Run it from a clean checkout of main (it pulls first). Windows Task Scheduler, Saturdays 08:00, one
task for all of them:

    schtasks /Create /SC WEEKLY /D SAT /ST 08:00 /TN "Kotihiiri local crawl" ^
      /TR "C:\\path\\to\\venv\\Scripts\\python.exe C:\\path\\to\\kotihiiri\\scripts\\crawl_local.py"

and, to work through the briefs backlog on the free daily quota, a daily task at 06:00 with the
same /TR plus `--briefs-only`:

    schtasks /Create /SC DAILY /ST 06:00 /TN "Kotihiiri briefs" /TR "... crawl_local.py --briefs-only"
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUCKET = "r2:kotihiiri-data"

# The CLI's help text has non-ASCII characters that a Windows console code page cannot print.
ENV = {**os.environ, "PYTHONUTF8": "1"}


def sh(*args: str, check: bool = True) -> int:
    print("+", " ".join(args), flush=True)
    return subprocess.run(args, cwd=ROOT, check=check, env=ENV).returncode


def kunta(*args: str) -> int:
    return sh(sys.executable, "-m", "kunta.cli", *args, check=False)


def local_municipalities() -> dict[str, bool]:
    """{slug: stored in git} for every enabled `crawl_from: local` municipality, in rank order."""
    sys.path.insert(0, str(ROOT))
    from kunta.config import load_cities

    return {
        slug: int(c.extra.get("rank", 99)) <= 6
        for slug, c in load_cities().items()
        if c.enabled and c.extra.get("crawl_from") == "local"
    }


def r2_ready() -> bool:
    if not shutil.which("rclone"):
        return False
    out = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True, env=ENV).stdout
    return "r2:" in out.split()


def ignore_locally(city: str) -> None:
    """Registry data lives in R2, never in git (§18.4): keep it out of `git status` on this machine."""
    exclude = ROOT / ".git" / "info" / "exclude"
    if not exclude.parent.exists():
        return
    lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
    want = [f"/data/{city}/", f"/data/state/{city}.json"]
    missing = [w for w in want if w not in lines]
    if missing:
        with exclude.open("a", encoding="utf-8") as f:
            f.write("".join(m + "\n" for m in missing))


def r2(*args: str) -> int:
    return sh("rclone", *args, "--s3-no-check-bucket", check=False)


SIX = {"helsinki", "espoo", "tampere", "vantaa", "oulu", "turku"}


def briefs(ok: list[str], cities: dict[str, bool], max_requests: int, use_r2: bool) -> list[str]:
    """AI briefs of new meetings (PLAN.md §20) for the six cities in git and the registry
    municipalities crawled in this run. Returns the municipalities whose briefs should be stored."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY not set; skipping AI briefs", file=sys.stderr)
        return []
    targets = sorted(c for c in SIX if (ROOT / "data" / c / "meetings").is_dir())
    targets += [c for c in ok if not cities[c] and use_r2]
    if not targets:
        return []
    kunta("briefs", "--city", ",".join(targets), "--max-requests", str(max_requests))
    for c in targets:
        if c not in SIX and (ROOT / "data" / c / "briefs").is_dir():
            r2("sync", f"data/{c}/briefs", f"{BUCKET}/data/{c}/briefs", "--checksum", "--fast-list")
    return targets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="*", help="slugs; default: every crawl_from: local municipality")
    ap.add_argument("--since", default="2025-01-01")
    ap.add_argument("--window", default="10", help="weeks to refetch, or `all`")
    ap.add_argument("--max-minutes", type=int, default=300, help="shared by all municipalities")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--briefs-only", action="store_true", help="skip the crawl; write AI briefs and push")
    ap.add_argument("--no-briefs", action="store_true", help="skip the AI briefs step")
    ap.add_argument("--briefs-requests", type=int, default=700, help="OpenRouter requests for briefs")
    a = ap.parse_args()

    if not a.no_push:
        sh("git", "checkout", a.branch)
        sh("git", "pull", "--ff-only", "origin", a.branch)

    known = local_municipalities()
    unknown = [c for c in a.cities if c not in known]
    if unknown:
        print(f"not enabled with crawl_from: local: {', '.join(unknown)}", file=sys.stderr)
        return 2
    cities = {c: known[c] for c in a.cities} if a.cities else known

    use_r2 = not a.no_push and any(not in_git for in_git in cities.values())
    if use_r2 and not r2_ready():
        print("registry municipalities need rclone with an `r2` remote; skipping them", file=sys.stderr)
        cities = {c: g for c, g in cities.items() if g}
        use_r2 = False

    start = time.monotonic()
    ok: list[str] = []
    failed: list[str] = []
    for city, in_git in ({} if a.briefs_only else cities).items():
        left = a.max_minutes - int((time.monotonic() - start) / 60)
        if left < 10:
            print(f"out of time before {city}; it continues next run", file=sys.stderr)
            break
        if use_r2 and not in_git:
            ignore_locally(city)
            r2("copy", f"{BUCKET}/data/{city}", f"data/{city}", "--checksum", "--fast-list")
            r2("copy", f"{BUCKET}/data/state/{city}.json", "data/state/")
        args = ["crawl", "--city", city, "--since", a.since, "--max-minutes", str(left)]
        if a.window != "all":
            args += ["--window-weeks", a.window]
        code = kunta(*args)
        if code != 0:
            print(f"{city}: crawl exited with {code} (2 = layout-change alarm); left out", file=sys.stderr)
            failed.append(city)
            continue
        kunta("people", "--city", city)
        if kunta("validate", "--city", city) != 0:
            print(f"{city}: validation failed; left out", file=sys.stderr)
            failed.append(city)
            continue
        if use_r2 and not in_git:
            state = f"data/state/{city}.json"
            sync = [
                "sync",
                f"data/{city}",
                f"{BUCKET}/data/{city}",
                "--checksum",
                "--fast-list",
                "--max-delete",
                "500",
            ]
            synced = r2(*sync) == 0 and r2("copy", state, f"{BUCKET}/data/state/", "--checksum") == 0
            if not synced:
                print(f"{city}: upload to R2 failed; left out", file=sys.stderr)
                failed.append(city)
                continue
        ok.append(city)

    print(f"ok: {' '.join(ok) or '-'}; failed: {' '.join(failed) or '-'}")

    briefed = [] if a.no_briefs else briefs(ok, cities, a.briefs_requests, use_r2)
    if a.no_push or not (ok or briefed):
        return 1 if failed else 0

    paths: list[str] = [f"data/{c}/briefs" for c in briefed if c in SIX]
    for city in ok:
        paths.append(f"config/bodies/{city}.yaml")
        if cities[city]:
            paths += [f"data/{city}", f"data/state/{city}.json"]
    sh("git", "add", "--", *[p for p in paths if (ROOT / p).exists()])
    if sh("git", "diff", "--cached", "--quiet", check=False) == 0:
        print("no changes to commit")
        return 1 if failed else 0
    what = f"local crawl {dt.date.today().isoformat()} ({', '.join(ok)})" if ok else "AI briefs"
    sh("git", "commit", "-m", f"data: {what}")
    for _ in range(3):
        pulled = sh("git", "pull", "--rebase", "-X", "theirs", "origin", a.branch, check=False) == 0
        if pulled and sh("git", "push", "origin", a.branch, check=False) == 0:
            return 1 if failed else 0
        sh("git", "rebase", "--abort", check=False)
    return 1


if __name__ == "__main__":
    sys.exit(main())
