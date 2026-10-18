"""Basic facts about each municipality from Statistics Finland's municipal key figures.

Source: "Kuntien avainluvut" (Municipal key figures), the table with the latest regional
division, `kuntien_avainluvut_viimeisin.px` on the PxWeb API (no robots.txt on the host). It
has one row per municipality and one value per figure: population, age groups, languages,
education, employment, jobs and so on, each for the latest year Statistics Finland has.

`kunta facts` writes site/src/data/municipality-facts.json for all 96 municipalities in
config/municipalities.yaml, with each figure's label in Finnish, Swedish and English and the
whole country's value for comparison. The file lives with the site because the site builds
from R2 data that does not carry it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .http import PoliteClient

log = logging.getLogger(__name__)

HOST = "pxdata.stat.fi"
TABLE = "kuntien_avainluvut_viimeisin"
# The API names the folder "uusin"; the web pages write database and folder as "…__uusin".
PATH = f"Kuntien_avainluvut/uusin/{TABLE}.px"
LANGS = ("fi", "sv", "en")
SOURCE_PAGE = (
    "https://pxdata.stat.fi/PxWeb/pxweb/{lang}/Kuntien_avainluvut/Kuntien_avainluvut__uusin/" + TABLE + ".px/"
)
TITLES = {"fi": "Kuntien avainluvut", "sv": "Kommunernas nyckeltal", "en": "Municipal key figures"}
COUNTRY_TEXTS = {"koko maa", "hela landet", "whole country"}


def api_url(lang: str) -> str:
    return f"https://{HOST}/PxWeb/api/v1/{lang}/{PATH}"


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def split_variables(meta: dict) -> tuple[dict, dict, list[dict]]:
    """(area variable, figures variable, any other variables) of the table metadata."""
    variables = meta["variables"]
    figures = next(
        (v for v in variables if v["code"].casefold() in ("tiedot", "contentscode")),
        None,
    ) or next(v for v in variables if _key(v["text"]) in ("tiedot", "uppgifter", "information"))
    area = next(
        (
            v
            for v in variables
            if v is not figures and _key(v["text"]) in ("alue", "område", "region", "area")
        ),
        None,
    ) or next(v for v in variables if v is not figures and not v.get("time"))
    rest = [v for v in variables if v is not figures and v is not area]
    return area, figures, rest


def match_areas(area: dict, municipalities: dict[str, dict]) -> tuple[dict[str, str], str | None]:
    """{our slug: area value code} by Finnish then Swedish name, and the whole country's code."""
    by_text: dict[str, str] = {}
    country = None
    for code, text in zip(area["values"], area["valueTexts"], strict=True):
        # Statistics Finland prints a few names differently: "Maarianhamina - Mariehamn" (both
        # languages) and "Pedersören kunta" (genitive, for Pedersöre).
        for part in [text, *text.split(" - ")]:
            by_text.setdefault(_key(part), code)
            m = re.fullmatch(r"(.+)n kunta", _key(part))
            if m:
                by_text.setdefault(m.group(1), code)
        if _key(text) in COUNTRY_TEXTS:
            country = code
    out: dict[str, str] = {}
    for slug, m in municipalities.items():
        for name in (m.get("name_fi"), m.get("name_sv")):
            if name and _key(name) in by_text:
                out[slug] = by_text[_key(name)]
                break
    return out, country


def query_body(area: dict, figures: dict, rest: list[dict], codes: list[str]) -> dict:
    query = [
        {"code": area["code"], "selection": {"filter": "item", "values": codes}},
        {"code": figures["code"], "selection": {"filter": "item", "values": list(figures["values"])}},
    ]
    # Any other dimension (none today): take its last value, the latest year.
    for v in rest:
        query.append({"code": v["code"], "selection": {"filter": "item", "values": [v["values"][-1]]}})
    return {"query": query, "response": {"format": "json-stat2"}}


def parse_jsonstat(data: dict, area_code: str, figures_code: str) -> dict[str, dict[str, Any]]:
    """{area value code: {figure code: number or None}} from a json-stat2 dataset."""
    ids: list[str] = data["id"]
    sizes: list[int] = data["size"]
    index = {d: data["dimension"][d]["category"]["index"] for d in ids}
    # index may be a list or a {code: position} dict in json-stat2.
    index = {
        d: (dict((c, i) for i, c in enumerate(ix)) if isinstance(ix, list) else ix) for d, ix in index.items()
    }
    values = data["value"]
    if isinstance(values, dict):
        values = [values.get(str(i)) for i in range(_product(sizes))]
    strides = []
    acc = 1
    for s in reversed(sizes):
        strides.append(acc)
        acc *= s
    strides.reverse()
    out: dict[str, dict[str, Any]] = {}
    # Any other dimension was queried with one value, so its position is 0.
    for a, ai in index[area_code].items():
        row: dict[str, Any] = {}
        for f, fi in index[figures_code].items():
            pos = strides[ids.index(area_code)] * ai + strides[ids.index(figures_code)] * fi
            row[f] = _number(values[pos])
        out[a] = row
    return out


def _product(xs: list[int]) -> int:
    n = 1
    for x in xs:
        n *= x
    return n


def _number(v: Any) -> int | float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return int(v) if float(v).is_integer() else round(float(v), 4)
    try:
        f = float(str(v).replace(",", "."))
    except ValueError:
        return None
    return int(f) if f.is_integer() else round(f, 4)


def decimals(data: dict, figures_code: str) -> dict[str, int]:
    cat = data["dimension"][figures_code]["category"]
    units = cat.get("unit") or {}
    return {code: int(u.get("decimals", 0)) for code, u in units.items() if isinstance(u, dict)}


def build(
    metas: dict[str, dict],
    data: dict,
    municipalities: dict[str, dict],
) -> dict:
    """The facts file from the table metadata in each language and the Finnish json-stat2 data."""
    area, figures, _rest = split_variables(metas["fi"])
    codes, country = match_areas(area, municipalities)
    rows = parse_jsonstat(data, area["code"], figures["code"])
    dec = decimals(data, figures["code"])
    labels: dict[str, dict[str, str]] = {code: {} for code in figures["values"]}
    for lang, meta in metas.items():
        _a, fig, _r = split_variables(meta)
        for code, text in zip(fig["values"], fig["valueTexts"], strict=True):
            if code in labels:
                labels[code][lang] = text.strip()
    figures_out = [
        {"code": code, "label": labels[code], "decimals": dec.get(code, 0), "order": i}
        for i, code in enumerate(figures["values"])
    ]
    out = {
        "source": {
            "publisher": "Tilastokeskus / Statistics Finland",
            "table": TABLE,
            "title": TITLES,
            "updated": data.get("updated"),
            "api_url": api_url("fi"),
            "page_url": {lang: SOURCE_PAGE.format(lang=lang) for lang in LANGS},
            "licence": "CC BY 4.0",
        },
        "figures": figures_out,
        "country": rows.get(country, {}) if country else {},
        "municipalities": {
            slug: {"area_code": code, "values": rows.get(code, {})} for slug, code in sorted(codes.items())
        },
    }
    return out


def fetch(client: PoliteClient, municipalities: dict[str, dict]) -> dict:
    metas = {lang: json.loads(client.get(api_url(lang)).text) for lang in LANGS}
    area, figures, rest = split_variables(metas["fi"])
    codes, country = match_areas(area, municipalities)
    missing = sorted(set(municipalities) - set(codes))
    if missing:
        log.warning("no key-figure row for: %s", ", ".join(missing))
    wanted = sorted(set(codes.values()) | ({country} if country else set()))
    resp = client.post_json(api_url("fi"), query_body(area, figures, rest, wanted))
    data = json.loads(resp.content.decode("utf-8-sig"))
    return build(metas, data, municipalities)
