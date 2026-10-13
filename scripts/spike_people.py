"""Temporary spike (removed before merge): where can council rosters with party come from?"""
import json
import sys

import httpx

from kunta.config import load_project
from kunta.http import PoliteClient

UA = load_project().user_agent
hosts = {"pxdata.stat.fi", "www.espoo.fi", "www.tampere.fi", "statfin.stat.fi"}
raw = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30)
for h in sorted(hosts):
    try:
        r = raw.get(f"https://{h}/robots.txt")
        print(f"=== robots {h} {r.status_code}\n{r.text[:1500]}")
    except Exception as e:  # noqa: BLE001
        print(f"=== robots {h} error {e}")

with PoliteClient(UA, allowed_hosts=hosts) as c:
    for url in sys.argv[1:]:
        try:
            r = c.get(url)
        except Exception as e:  # noqa: BLE001
            print(f"=== {url} ERROR {type(e).__name__} {e}")
            continue
        print(f"=== {url} {r.status} {r.content_type} {len(r.content)}")
        body = r.text
        if "json" in r.content_type:
            try:
                body = json.dumps(json.loads(body), ensure_ascii=False)[:20000]
            except ValueError:
                pass
        print(body[:20000])
