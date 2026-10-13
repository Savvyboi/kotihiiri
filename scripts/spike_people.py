"""Temporary spike (removed before merge): where can council rosters with party come from?"""
import json
import re
import sys

import httpx

from kunta.config import load_project
from kunta.http import PoliteClient

UA = load_project().user_agent
hosts = {"pxdata.stat.fi", "www.espoo.fi", "www.tampere.fi"}
raw = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30)
for h in sorted(hosts):
    r = raw.get(f"https://{h}/robots.txt")
    lines = [ln for ln in r.text.splitlines() if ln.strip() and not ln.startswith("#")]
    print(f"=== robots {h} {r.status_code}: " + " | ".join(lines[:60]))


def text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|head|svg|nav|header|footer)\b.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


with PoliteClient(UA, allowed_hosts=hosts) as c:
    for url in sys.argv[1:]:
        try:
            r = c.get(url)
        except Exception as e:  # noqa: BLE001
            print(f"=== {url} ERROR {type(e).__name__} {e}")
            continue
        print(f"=== {url} {r.status} {r.content_type} {len(r.content)}")
        if "json" in r.content_type:
            data = json.loads(r.text)
            if isinstance(data, list):
                for row in data:
                    print(" ", json.dumps(row, ensure_ascii=False)[:300])
            else:
                print(json.dumps(data, ensure_ascii=False)[:6000])
        else:
            t = text(r.text)
            print(t[:6000])
            for kw in ("valtuute", "Kok", "SDP", "Vihr", "jäsenet"):
                for m in list(re.finditer(kw, t))[:3]:
                    print(f"  [{kw}] …{t[max(0, m.start()-200):m.start()+300]}…")
