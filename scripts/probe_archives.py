"""One-off probe (PLAN.md M14): do public web archives hold the Tweb hosts' minutes?

For each Tweb host that the robots audit blocked or could not reach, prints the robots.txt text,
then asks the Common Crawl index (last few crawls) and the Internet Archive's CDX API how many
captures they hold of the minutes and agenda pages. Reads only the archives' index APIs and
robots.txt; fetches no meeting or item page from any municipal host. Output goes to the log.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "KuntaDataBot/0.1 (+https://kotihiiri.eu/tietoa; archive probe)"
CC_CRAWLS = 2


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:  # noqa: BLE001
        return None, repr(e)


def main():
    hosts = json.loads(Path("data/state/robots.json").read_text())["hosts"]
    tweb = sorted(
        h
        for h, v in hosts.items()
        if v["status"] != "allowed"
        and v["status"] != "no_robots"
        and h not in ("paatokset.turku.fi", "ah.turku.fi")
    )
    print(f"{len(tweb)} hosts")
    _, colls = get("https://index.commoncrawl.org/collinfo.json")
    crawls = [c["id"] for c in json.loads(colls)[:CC_CRAWLS]]
    print("Common Crawl crawls:", crawls)
    shown = set()
    for host in tweb:
        print(f"\n===== {host}")
        status, robots = get(f"https://{host}/robots.txt", timeout=20)
        key = robots.strip()
        if key in shown:
            print(f"robots.txt {status}: same as an earlier host")
        else:
            shown.add(key)
            print(f"robots.txt {status}:\n{robots[:1500]}")
        for crawl in crawls:
            q = urllib.parse.urlencode({"url": f"{host}/*", "output": "json", "limit": "2000"})
            st, body = get(f"https://index.commoncrawl.org/{crawl}-index?{q}")
            lines = [json.loads(x) for x in body.splitlines() if x.startswith("{")] if st == 200 else []
            mins = [x for x in lines if "pk_" in x["url"] or "epj_" in x["url"] or "fileshow" in x["url"]]
            print(f"CC {crawl}: http {st}, {len(lines)} captures, {len(mins)} minutes/agenda/doc")
            for x in mins[:3]:
                print("   ", x.get("status"), x["url"])
            time.sleep(1.5)
        q = urllib.parse.urlencode(
            {
                "url": f"{host}/*",
                "from": "2025",
                "output": "json",
                "limit": "5000",
                "fl": "timestamp,original,statuscode",
                "collapse": "urlkey",
            }
        )
        st, body = get(f"https://web.archive.org/cdx/search/cdx?{q}", timeout=60)
        rows = json.loads(body)[1:] if st == 200 and body.strip().startswith("[") else []
        mins = [r for r in rows if "pk_" in r[1] or "fileshow" in r[1]]
        print(f"Wayback since 2025: http {st}, {len(rows)} distinct URLs, {len(mins)} minutes/doc")
        for r in mins[:3]:
            print("   ", r)
        time.sleep(1.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
