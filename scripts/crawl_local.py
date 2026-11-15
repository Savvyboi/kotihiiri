"""Weekly crawl of a `crawl_from: local` municipality from a home connection (Turku, PLAN.md §7.6).

Turku's hosts do not answer GitHub's servers, so this does on Savvas's computer what the weekly
workflow's crawl and commit jobs do for the other six cities: crawl, roster, validate, then commit
data/{city}, its crawl state and body config, and push. Nothing is committed if the crawl raised a
layout alarm or validation failed. The site picks the data up on the next deploy.

    python scripts/crawl_local.py turku                 # weekly: last 10 weeks, then push to main
    python scripts/crawl_local.py turku --window all    # first run / full refresh
    python scripts/crawl_local.py turku --no-push       # crawl and validate only

Run it from a clean checkout of main (it pulls first). Windows Task Scheduler, Saturdays 08:00:

    schtasks /Create /SC WEEKLY /D SAT /ST 08:00 /TN "Kotihiiri Turku" ^
      /TR "C:\\path\\to\\venv\\Scripts\\python.exe C:\\path\\to\\kotihiiri\\scripts\\crawl_local.py turku"
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# The CLI's help text has non-ASCII characters that a Windows console code page cannot print.
ENV = {**os.environ, "PYTHONUTF8": "1"}


def sh(*args: str, check: bool = True) -> int:
    print("+", " ".join(args), flush=True)
    return subprocess.run(args, cwd=ROOT, check=check, env=ENV).returncode


def kunta(*args: str) -> int:
    return sh(sys.executable, "-m", "kunta.cli", *args, check=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("--since", default="2025-01-01")
    ap.add_argument("--window", default="10", help="weeks to refetch, or `all`")
    ap.add_argument("--max-minutes", default="300")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()

    if not a.no_push:
        sh("git", "checkout", a.branch)
        sh("git", "pull", "--ff-only", "origin", a.branch)

    args = ["crawl", "--city", a.city, "--since", a.since, "--max-minutes", a.max_minutes]
    if a.window != "all":
        args += ["--window-weeks", a.window]
    code = kunta(*args)
    if code != 0:
        print(f"crawl exited with {code} (2 = layout-change alarm); nothing committed", file=sys.stderr)
        return code
    kunta("people", "--city", a.city)
    if kunta("validate", "--city", a.city) != 0:
        print("validation failed; nothing committed", file=sys.stderr)
        return 1
    if a.no_push:
        return 0

    paths = [f"data/{a.city}", f"data/state/{a.city}.json", f"config/bodies/{a.city}.yaml"]
    sh("git", "add", "--", *[p for p in paths if (ROOT / p).exists()])
    if sh("git", "diff", "--cached", "--quiet", check=False) == 0:
        print("no changes")
        return 0
    sh("git", "commit", "-m", f"data: {a.city} crawl from local {dt.date.today().isoformat()}")
    for _ in range(3):
        pulled = sh("git", "pull", "--rebase", "-X", "theirs", "origin", a.branch, check=False) == 0
        if pulled and sh("git", "push", "origin", a.branch, check=False) == 0:
            return 0
        sh("git", "rebase", "--abort", check=False)
    return 1


if __name__ == "__main__":
    sys.exit(main())
