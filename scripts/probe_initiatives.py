"""One-off probe: what does the kuntalaisaloite.fi open API return? Output is the job log only.

Goes through the polite client, so robots.txt and the rate limit apply.
"""

from __future__ import annotations

import json
import re

from kunta.config import load_project
from kunta.http import PoliteClient, RobotsDisallowed

HOST = "www.kuntalaisaloite.fi"
BASE = f"https://{HOST}"


def show(client: PoliteClient, path: str, limit: int = 6000) -> object | None:
    url = BASE + path
    try:
        resp = client.get(url)
    except RobotsDisallowed:
        print(f"===== {path}: skipped_robots")
        return None
    except Exception as e:  # noqa: BLE001 - probe
        print(f"===== {path}: {type(e).__name__} {e}")
        return None
    print(f"===== {path}: {resp.status} {resp.content_type} {len(resp.content)} bytes {resp.headers}")
    text = resp.text
    if "html" in resp.content_type:
        text = re.sub(r"(?is)<(script|style|head|svg)\b.*?</\1>", "", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
    print(text[:limit])
    try:
        return json.loads(resp.content)
    except ValueError:
        return None


def main() -> None:
    with PoliteClient(load_project().user_agent, allowed_hosts={HOST}) as client:
        try:
            print(client.get(BASE + "/robots.txt").text)
        except Exception as e:  # noqa: BLE001
            print("robots", e)
        show(client, "/api", 20000)
        show(client, "/fi/api", 20000)
        munis = show(client, "/api/v1/municipalities", 3000)
        if isinstance(munis, list):
            print("municipalities:", len(munis))
            show(client, f"/api/v1/municipalities/{munis[0].get('id')}", 3000)
        lst = show(client, "/api/v1/initiatives?limit=3", 6000)
        show(client, "/api/v1/initiatives?limit=3&offset=3&orderBy=latest", 3000)
        show(client, "/api/v1/initiatives?limit=2&municipality=91", 3000)
        if isinstance(lst, list) and lst:
            for it in lst[:3]:
                ident = it.get("id")
                if isinstance(ident, str) and ident.startswith("http"):
                    path = ident.split(HOST, 1)[-1]
                else:
                    path = f"/api/v1/initiatives/{ident}"
                show(client, path, 8000)
        # how many exist: page with a large offset
        for off in (1000, 5000, 10000, 20000):
            r = show(client, f"/api/v1/initiatives?limit=1&offset={off}", 600)
            print("offset", off, "->", len(r) if isinstance(r, list) else r)


if __name__ == "__main__":
    main()
