"""Temporary spike (removed before merge): StatFin candidate tables."""
import json

from kunta.config import load_project
from kunta.http import PoliteClient

UA = load_project().user_agent
BASE = "https://pxdata.stat.fi/PxWeb/api/v1/fi/StatFin/kvaa/"
with PoliteClient(UA, allowed_hosts={"pxdata.stat.fi"}) as c:
    for table, town in (("statfin_kvaa_pxt_14ux.px", "Espoo"), ("statfin_kvaa_pxt_14v2.px", "Tampere"),
                        ("statfin_kvaa_pxt_14uk.px", "Helsinki")):
        r = c.get(BASE + table)
        print(f"=== {table} {r.status} {len(r.content)}")
        if r.status != 200:
            r = c.get(BASE + table.replace("statfin_kvaa_pxt_", ""))
            print(f"=== retry short id {r.status} {len(r.content)} {r.text[:300]}")
            if r.status != 200:
                continue
        meta = json.loads(r.text)
        print("title:", meta.get("title"))
        query = []
        for v in meta["variables"]:
            vals = list(zip(v["values"], v["valueTexts"]))
            print(f"  var {v['code']!r} {v['text']!r} n={len(vals)} first={vals[:6]}")
            hits = [x for x in vals if town in x[1]]
            if hits and len(vals) < 2000:
                print(f"    {town} values: {hits[:10]}")
                query.append({"code": v["code"], "selection": {"filter": "item", "values": [hits[0][0]]}})
        r = c.post_json(r.url, {"query": query, "response": {"format": "csv"}})
        print(f"=== data {r.status} {len(r.content)}")
        lines = r.text.splitlines()
        print(f"  lines={len(lines)}")
        for ln in lines[:40]:
            print("  ", ln)
