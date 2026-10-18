"""Fetch municipality boundaries from Statistics Finland and write the site map file.

Writes site/src/data/municipality-map.json (see kunta/mapdata.py). Run by
.github/workflows/municipality-map.yml; the build environment has no route to geo.stat.fi.
Three requests through the polite client (robots.txt checked, 1 request/second).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from kunta import jsonio
from kunta.config import load_project
from kunta.http import PoliteClient
from kunta.mapdata import INSET_BBOX, WFS, build_map, capabilities_layers, feature_url, newest_layer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "src" / "data" / "municipality-map.json"


def main() -> None:
    munis = yaml.safe_load((ROOT / "config" / "municipalities.yaml").read_text(encoding="utf-8"))[
        "municipalities"
    ]
    host = WFS.split("://", 1)[1].split("/", 1)[0]
    with PoliteClient(load_project().user_agent + " municipality-map", allowed_hosts={host}) as client:
        caps = client.get(f"{WFS}?service=WFS&version=2.0.0&request=GetCapabilities").text
        layers = capabilities_layers(caps)
        country_layer, year = newest_layer(layers, "4500k")
        inset_layer, inset_year = newest_layer(layers, "1000k")
        if inset_year != year:
            sys.exit(f"layer years differ: {country_layer} vs {inset_layer}")
        country = json.loads(client.get(feature_url(country_layer)).text)
        inset = json.loads(client.get(feature_url(inset_layer, INSET_BBOX)).text)
    data = build_map(country, inset, munis, year=year, layers=[country_layer, inset_layer])
    jsonio.write(OUT, data)
    n = len(data["municipalities"])
    print(f"{OUT.relative_to(ROOT)}: {n} municipalities ({year}), {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
