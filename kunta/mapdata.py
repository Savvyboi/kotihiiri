"""Municipality boundaries for the site map (/kartta/), from Statistics Finland's open WFS.

Statistics Finland publishes the statistical municipality division each year as open data
(CC BY 4.0) at geo.stat.fi. Two layers are used:

- `kunta4500k_{year}`, generalized for 1:4,500,000, for the whole country;
- `kunta1000k_{year}`, generalized for 1:1,000,000, for the capital-region inset, where the
  municipalities are too small to see on the whole-country map.

Both are fetched in ETRS-TM35FIN (EPSG:3067), a planar projection in metres, so the coordinates
become SVG coordinates by flipping the y axis; no map projection library is needed. Output is
`site/src/data/municipality-map.json`: one SVG path per municipality, in units of 100 m, with
the municipality code and names. Same input gives byte-identical output (PLAN.md §2.2 rule 10).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

WFS = "https://geo.stat.fi/geoserver/tilastointialueet/wfs"
SOURCE_NAME = "Tilastokeskus, kuntajako (geo.stat.fi)"
LICENCE = "CC BY 4.0"
UNIT_M = 100  # one SVG unit = 100 m

# Capital-region inset in EPSG:3067 metres (min E, min N, max E, max N): Kirkkonummi to Sipoo,
# the coast to Nurmijärvi and Järvenpää.
INSET_BBOX = (352_000, 6_660_000, 418_000, 6_718_000)


def capabilities_layers(xml: str) -> list[str]:
    """Feature type names listed in a WFS GetCapabilities document."""
    return sorted(set(re.findall(r"<(?:wfs:)?Name>([^<]+)</(?:wfs:)?Name>", xml)))


def newest_layer(layers: Iterable[str], scale: str) -> tuple[str, int]:
    """Newest `tilastointialueet:kunta{scale}_{year}` layer, e.g. scale `4500k`."""
    pat = re.compile(rf"^(?:tilastointialueet:)?kunta{scale}_(\d{{4}})$")
    found = sorted((int(m.group(1)), name) for name in layers if (m := pat.match(name)))
    if not found:
        raise ValueError(f"no kunta{scale} layer in the WFS capabilities")
    year, name = found[-1]
    return (name if ":" in name else f"tilastointialueet:{name}"), year


def feature_url(layer: str, bbox: tuple[int, int, int, int] | None = None) -> str:
    url = (
        f"{WFS}?service=WFS&version=2.0.0&request=GetFeature&typeNames={layer}"
        "&outputFormat=application/json&srsName=EPSG:3067"
    )
    if bbox:
        url += "&bbox=" + ",".join(str(v) for v in bbox) + ",EPSG:3067"
    return url


def _rings(geometry: dict) -> list[list[list[float]]]:
    if geometry["type"] == "Polygon":
        return list(geometry["coordinates"])
    if geometry["type"] == "MultiPolygon":
        return [ring for poly in geometry["coordinates"] for ring in poly]
    raise ValueError(f"unexpected geometry {geometry['type']}")


def _is_planar(rings: list[list[list[float]]]) -> bool:
    x, y = rings[0][0][:2]
    return 50_000 < x < 800_000 and 6_500_000 < y < 7_900_000


def svg_path(geometry: dict, origin: tuple[int, int]) -> str:
    """SVG path data for a (Multi)Polygon in EPSG:3067, in UNIT_M units from `origin` (min E, max N).

    Coordinates are rounded to whole units before taking differences, so relative moves never drift.
    """
    rings = _rings(geometry)
    if not _is_planar(rings):
        raise ValueError("coordinates are not EPSG:3067 metres (was srsName ignored?)")
    ox, oy = origin
    parts: list[str] = []
    for ring in rings:
        pts: list[tuple[int, int]] = []
        for x, y, *_ in ring:
            p = (round((x - ox) / UNIT_M), round((oy - y) / UNIT_M))
            if not pts or p != pts[-1]:
                pts.append(p)
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) < 3:
            continue  # an islet smaller than one unit
        cmd = [f"M{pts[0][0]} {pts[0][1]}l"]
        prev = pts[0]
        steps = []
        for p in pts[1:]:
            steps.append(f"{p[0] - prev[0]} {p[1] - prev[1]}")
            prev = p
        parts.append(cmd[0] + " ".join(steps) + "z")
    # SVG accepts "1 -2" as "1-2"; drop the space before a minus to save bytes.
    return re.sub(r" -", "-", "".join(parts))


def fold(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch)).strip()


def match_ids(features: list[dict], municipalities: dict[str, dict]) -> dict[str, str]:
    """Municipality code → our id (config/municipalities.yaml), matched on Finnish or Swedish name.

    Raises if any of our municipalities finds no boundary, so a rename can't silently drop one.
    """
    by_name: dict[str, str] = {}
    for f in features:
        p = f["properties"]
        for key in ("nimi", "namn"):
            for part in str(p.get(key) or "").split(" - "):
                if part.strip():
                    by_name.setdefault(fold(part), p["kunta"])
    out: dict[str, str] = {}
    missing = []
    for mid, m in municipalities.items():
        code = next(
            (by_name[fold(n)] for n in (m.get("name_fi"), m.get("name_sv")) if n and fold(n) in by_name), None
        )
        if code is None:
            missing.append(mid)
        else:
            out[code] = mid
    if missing:
        raise ValueError("no boundary found for: " + ", ".join(sorted(missing)))
    return out


def _bounds(features: list[dict]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for f in features:
        for ring in _rings(f["geometry"]):
            for x, y, *_ in ring:
                xs.append(x)
                ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def build_map(
    country: dict,
    inset: dict | None,
    municipalities: dict[str, dict],
    *,
    year: int,
    layers: list[str],
) -> dict:
    """The site's map file from the two GeoJSON FeatureCollections."""
    feats = sorted(country["features"], key=lambda f: f["properties"]["kunta"])
    ids = match_ids(feats, municipalities)
    minx, miny, maxx, maxy = _bounds(feats)
    origin = (int(minx // UNIT_M * UNIT_M), int(-(-maxy // UNIT_M) * UNIT_M))
    width = round((maxx - origin[0]) / UNIT_M) + 1
    height = round((origin[1] - miny) / UNIT_M) + 1

    def rows(fs: list[dict]) -> list[dict]:
        out = []
        for f in sorted(fs, key=lambda f: f["properties"]["kunta"]):
            p = f["properties"]
            row = {"code": p["kunta"], "name_fi": p.get("nimi") or "", "d": svg_path(f["geometry"], origin)}
            if p.get("namn") and p.get("namn") != p.get("nimi"):
                row["name_sv"] = p["namn"]
            if p["kunta"] in ids:
                row["id"] = ids[p["kunta"]]
            out.append(row)
        return out

    result = {
        "source": SOURCE_NAME,
        "source_url": WFS,
        "licence": LICENCE,
        "year": year,
        "layers": layers,
        "unit_m": UNIT_M,
        "viewbox": [0, 0, width, height],
        "municipalities": rows(feats),
    }
    if inset is not None:
        bx0, by0, bx1, by1 = INSET_BBOX
        result["inset"] = {
            "viewbox": [
                round((bx0 - origin[0]) / UNIT_M),
                round((origin[1] - by1) / UNIT_M),
                round((bx1 - bx0) / UNIT_M),
                round((by1 - by0) / UNIT_M),
            ],
            "municipalities": rows(inset["features"]),
        }
    return result
