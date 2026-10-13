"""Fetch a few public pages through the polite client and save them for fixture work.

Run from `.github/workflows/record-pages.yml`; the files go into a workflow artifact, never into
git (PLAN.md §2.2 rule 6). Used to replace reconstructed fixtures with recorded ones (§14).
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from kunta.config import load_cities, load_project, require_enabled
from kunta.http import PoliteClient
from kunta.pdf import pdf_pages


def compact(html: str) -> str:
    """Body markup without scripts, styles or attributes other than href/class/id/value (option values
    carry Tweb body ids)."""
    html = re.sub(r"(?is)<(script|style|head|svg)\b.*?</\1>", "", html)
    html = re.sub(r"(?is)<!--.*?-->", "", html)

    def attrs(m: re.Match) -> str:
        kept = re.findall(r'\s(?:href|class|id|value)=("[^"]*"|\'[^\']*\')', m.group(2))
        names = re.findall(r"\s(href|class|id|value)=(?:\"[^\"]*\"|'[^']*')", m.group(2))
        return f"<{m.group(1)}" + "".join(f" {n}={v}" for n, v in zip(names, kept, strict=False)) + ">"

    tag = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*)?>")
    html = tag.sub(lambda m: attrs(m) if m.group(2) else m.group(0), html)
    return re.sub(r"\s+", " ", html).replace("> <", "><")


def main(city: str, out: str, urls: list[str]) -> None:
    # "enabled" allows the hosts of every enabled city; Oulu and Turku stay out either way.
    cfgs = [c for c in load_cities().values() if c.enabled] if city == "enabled" else [require_enabled(city)]
    hosts = {u.split("://", 1)[1].split("/", 1)[0] for c in cfgs for u in c.base_urls}
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with PoliteClient(load_project().user_agent, allowed_hosts=hosts) as client:
        for url in urls:
            resp = client.get(url)
            path = url.split("://", 1)[1].split("/", 1)[-1].replace("cgi/DREQUEST.PHP?", "")
            name = re.sub(r"[^\w.-]+", "_", path).strip("_")
            name = name[:80] or hashlib.sha256(url.encode()).hexdigest()[:12]
            (out_dir / name).write_bytes(resp.content)
            print(f"{resp.status} {resp.content_type} {len(resp.content)} {url} -> {name}")
            # Also into the log, which is readable where artifact storage is not.
            print(f"=====BEGIN {name}")
            if resp.content.startswith(b"%PDF"):
                for i, page in enumerate(pdf_pages(resp.content), start=1):
                    print(f"--- page {i}")
                    print("\n".join(page))
            else:
                print(compact(resp.text))
            print(f"=====END {name}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
