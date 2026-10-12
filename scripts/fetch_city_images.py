"""Fetch each city's coat of arms and a public-domain hero photo from Wikimedia Commons.

Reads config/images.yaml, writes site/public/images/cities/{city}-arms.svg,
{city}-photo-{1920,960}.jpg and site/src/data/city-images.json (source, author, licence per file).
Run by .github/workflows/city-images.yml; the build environment has no route to Wikimedia.

Only the Wikidata and Commons APIs are used, one request per second, with the project
User-Agent (Wikimedia's User-Agent policy asks for a contact address).
"""

from __future__ import annotations

import html
import io
import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "site" / "public" / "images" / "cities"
CREDITS = ROOT / "site" / "src" / "data" / "city-images.json"
COMMONS = "https://commons.wikimedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"
# Structured-data filter: licence CC0 or copyright status public domain.
FREE_FILTER = "haswbstatement:P275=Q6938433|P6216=Q19652 -map -kartta -karta"
PHOTO_WIDTHS = (1920, 960)
MIN_WIDTH = 1920


class Api:
    def __init__(self, user_agent: str) -> None:
        self.client = httpx.Client(headers={"User-Agent": user_agent}, timeout=60, follow_redirects=True)
        self.last = 0.0

    def get(self, url: str, **params) -> httpx.Response:
        wait = 1.0 - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        resp = self.client.get(url, params=params or None)
        resp.raise_for_status()
        return resp

    def json(self, url: str, **params) -> dict:
        return self.get(url, format="json", formatversion="2", **params).json()


def plain(value: str | None) -> str:
    """Commons extmetadata values are HTML fragments."""
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def wikidata_arms(api: Api, fiwiki: str) -> str:
    data = api.json(WIKIDATA, action="wbgetentities", sites="fiwiki", titles=fiwiki, props="claims")
    (entity,) = data["entities"].values()
    claims = entity.get("claims", {})
    countries = {c["mainsnak"]["datavalue"]["value"]["id"] for c in claims.get("P17", [])}
    if "Q33" not in countries:  # Finland
        raise SystemExit(f"{fiwiki}: Wikidata item {entity['id']} is not in Finland")
    arms = [c for c in claims.get("P94", []) if c.get("rank") != "deprecated"]
    arms.sort(key=lambda c: c.get("rank") != "preferred")
    if not arms:
        raise SystemExit(f"{fiwiki}: no coat of arms (P94) on {entity['id']}")
    return arms[0]["mainsnak"]["datavalue"]["value"]


def file_info(api: Api, title: str, width: int | None = None) -> dict:
    title = title if title.startswith("File:") else f"File:{title}"
    params = {
        "action": "query",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|size|sha1|mime|extmetadata",
    }
    if width:
        params["iiurlwidth"] = str(width)
    page = api.json(COMMONS, **params)["query"]["pages"][0]
    if page.get("missing"):
        raise SystemExit(f"{title}: not on Commons")
    info = page["imageinfo"][0]
    meta = info.get("extmetadata", {})
    return {
        "title": page["title"],
        "page_url": info["descriptionurl"],
        "url": info["url"],
        "thumb_url": info.get("thumburl"),
        "mime": info["mime"],
        "width": info["width"],
        "height": info["height"],
        "sha1": info["sha1"],
        "licence": plain(meta.get("License", {}).get("value")).lower(),
        "licence_name": plain(meta.get("LicenseShortName", {}).get("value")),
        "licence_url": plain(meta.get("LicenseUrl", {}).get("value")) or None,
        "author": plain(meta.get("Artist", {}).get("value")) or None,
        "credit": plain(meta.get("Credit", {}).get("value")) or None,
        "description": plain(meta.get("ImageDescription", {}).get("value"))[:300] or None,
    }


def licence_ok(info: dict, allowed: list[str]) -> bool:
    lic = info["licence"]
    return lic in allowed or any(lic.startswith(a + "-") for a in allowed)


def search_photos(api: Api, query: str) -> list[str]:
    data = api.json(
        COMMONS,
        action="query",
        list="search",
        srnamespace="6",
        srlimit="40",
        srsearch=f"{query} filetype:bitmap {FREE_FILTER}",
    )
    return [r["title"] for r in data["query"]["search"]]


def pick_photo(api: Api, city: str, cfg: dict, allowed: list[str]) -> dict:
    if cfg.get("photo_file"):
        info = file_info(api, cfg["photo_file"], PHOTO_WIDTHS[0])
        if not licence_ok(info, allowed):
            raise SystemExit(f"{city}: pinned photo {info['title']} has licence {info['licence']!r}")
        return info
    exclude = {t if t.startswith("File:") else f"File:{t}" for t in cfg.get("photo_exclude") or []}
    for query in cfg.get("photo_queries") or []:
        titles = [t for t in search_photos(api, query) if t not in exclude]
        print(f"  {city}: {len(titles)} candidates for {query!r}")
        for title in titles:
            info = file_info(api, title, PHOTO_WIDTHS[0])
            ok = is_candidate(info, allowed)
            print(
                f"    {'PICK' if ok else 'skip'} {title} {info['width']}x{info['height']} {info['licence']}"
            )
            if ok:
                return info
    raise SystemExit(f"{city}: no photo with an allowed licence found; pin one with photo_file")


def is_candidate(info: dict, allowed: list[str]) -> bool:
    return (
        info["mime"] == "image/jpeg"
        and info["width"] >= MIN_WIDTH
        and info["width"] >= 1.3 * info["height"]
        and licence_ok(info, allowed)
    )


def review_sheet(api: Api, city: str, cfg: dict, allowed: list[str]) -> None:
    """Contact sheet of up to nine candidates in review/{city}.jpg (uploaded as a CI artifact)."""
    from PIL import ImageDraw

    exclude = {t if t.startswith("File:") else f"File:{t}" for t in cfg.get("photo_exclude") or []}
    picks: list[dict] = []
    for query in cfg.get("photo_queries") or []:
        for title in search_photos(api, query):
            if len(picks) >= 9 or title in exclude or any(p["title"] == title for p in picks):
                continue
            info = file_info(api, title, 500)
            if is_candidate(info, allowed):
                picks.append(info)
    sheet = Image.new("RGB", (3 * 500, 3 * 360), "white")
    draw = ImageDraw.Draw(sheet)
    for i, info in enumerate(picks):
        img = Image.open(io.BytesIO(api.get(info["thumb_url"]).content)).convert("RGB")
        img.thumbnail((496, 330))
        x, y = (i % 3) * 500, (i // 3) * 360
        sheet.paste(img, (x, y))
        draw.text((x + 4, y + 334), f"{i + 1}. {info['title'][5:60]}", fill="black")
        print(f"  review {i + 1}: {info['title']} | {info['licence']} | {info['description']}")
    (ROOT / "review").mkdir(exist_ok=True)
    sheet.save(ROOT / "review" / f"{city}.jpg", "JPEG", quality=80)


def save_photo(api: Api, city: str, info: dict) -> None:
    for width in PHOTO_WIDTHS:
        data = file_info(api, info["title"], width)
        raw = api.get(data["thumb_url"]).content
        img = Image.open(io.BytesIO(raw)).convert("RGB")  # drops EXIF, incl. GPS
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
        img.save(OUT_DIR / f"{city}-photo-{width}.jpg", "JPEG", quality=78, optimize=True, progressive=True)


def save_arms(api: Api, city: str, info: dict) -> None:
    svg = api.get(info["url"]).text
    if info["mime"] != "image/svg+xml" or "<svg" not in svg:
        raise SystemExit(f"{city}: arms {info['title']} is not an SVG")
    # Served through <img>, where scripts never run; strip them anyway.
    svg = re.sub(r"<script\b.*?</script>", "", svg, flags=re.S | re.I)
    svg = re.sub(r"\son\w+=\"[^\"]*\"", "", svg)
    (OUT_DIR / f"{city}-arms.svg").write_text(svg, encoding="utf-8")


def credit(info: dict, files: list[str]) -> dict:
    keep = (
        "title",
        "page_url",
        "sha1",
        "width",
        "height",
        "licence",
        "licence_name",
        "licence_url",
        "author",
    )
    return {k: info[k] for k in keep} | {"files": files}


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config" / "images.yaml").read_text(encoding="utf-8"))
    project = yaml.safe_load((ROOT / "config" / "project.yaml").read_text(encoding="utf-8"))
    ua = project["user_agent_template"].format(**project) + " city-images"
    only = set(sys.argv[1:])
    api = Api(ua)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CREDITS.parent.mkdir(parents=True, exist_ok=True)
    credits = json.loads(CREDITS.read_text(encoding="utf-8")) if CREDITS.exists() else {}

    for city, c in cfg["cities"].items():
        if only and city not in only:
            continue
        print(f"{city}:")
        if c.get("review"):
            review_sheet(api, city, c, cfg["licences"]["photo"])
            continue
        arms_title = c.get("arms_file") or wikidata_arms(api, c["fiwiki"])
        arms = file_info(api, arms_title)
        if not licence_ok(arms, cfg["licences"]["arms"]):
            raise SystemExit(f"{city}: arms {arms['title']} has licence {arms['licence']!r}")
        print(f"  arms {arms['title']} ({arms['licence']})")
        save_arms(api, city, arms)

        photo = pick_photo(api, city, c, cfg["licences"]["photo"])
        print(f"  photo {photo['title']} ({photo['licence']}) {photo['description']}")
        save_photo(api, city, photo)
        credits[city] = {
            "arms": credit(arms, [f"{city}-arms.svg"]),
            "photo": credit(photo, [f"{city}-photo-{w}.jpg" for w in PHOTO_WIDTHS])
            | {"description": photo["description"]},
        }

    CREDITS.write_text(
        json.dumps(credits, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
