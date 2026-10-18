import json

import httpx

from kunta import facts, jsonio
from kunta.http import PoliteClient, RateLimiter

UA = "KuntaDataBot/0.1 (+https://example.org/tietoa; test@example.org)"

# Shapes as the PxWeb v1 API prints them (metadata GET, json-stat2 POST); values made up.
AREAS = ["SSS", "KU091", "KU049", "KU710"]
FIGURES = ["M411", "M391"]
TEXTS = {
    "fi": (
        ["KOKO MAA", "Helsinki", "Espoo", "Raasepori"],
        ["Väkiluku, 2025", "Ruotsinkielisten osuus väestöstä, %, 2025"],
    ),
    "sv": (
        ["HELA LANDET", "Helsingfors", "Esbo", "Raseborg"],
        ["Folkmängd, 2025", "Andel svenskspråkiga, %, 2025"],
    ),
    "en": (
        ["WHOLE COUNTRY", "Helsinki", "Espoo", "Raseborg"],
        ["Population, 2025", "Swedish-speaking, %, 2025"],
    ),
}
MUNICIPALITIES = {
    "helsinki": {"name_fi": "Helsinki", "name_sv": "Helsingfors"},
    "espoo": {"name_fi": "Espoo", "name_sv": "Esbo"},
    "raasepori": {"name_fi": "Raasepori", "name_sv": "Raseborg"},
    "maarianhamina": {"name_fi": "Maarianhamina", "name_sv": "Mariehamn"},
}


def meta(lang):
    areas, figs = TEXTS[lang]
    return {
        "title": {"fi": "Kuntien avainluvut", "sv": "Kommunernas nyckeltal", "en": "Municipal key figures"}[
            lang
        ],
        "variables": [
            {
                "code": "Alue",
                "text": {"fi": "Alue", "sv": "Område", "en": "Region"}[lang],
                "values": AREAS,
                "valueTexts": areas,
            },
            {
                "code": "Tiedot",
                "text": {"fi": "Tiedot", "sv": "Uppgifter", "en": "Information"}[lang],
                "values": FIGURES,
                "valueTexts": figs,
            },
        ],
    }


def dataset(areas):
    full = {
        "SSS": [5_650_000, 5.1],
        "KU091": [690_000, 5.7],
        "KU049": [320_000, 6.6],
        "KU710": [27_000, "61.2"],
    }
    return {
        "class": "dataset",
        "updated": "2026-04-13T05:00:00Z",
        "id": ["Alue", "Tiedot"],
        "size": [len(areas), len(FIGURES)],
        "dimension": {
            "Alue": {"category": {"index": {a: i for i, a in enumerate(areas)}}},
            "Tiedot": {
                "category": {
                    "index": {f: i for i, f in enumerate(FIGURES)},
                    "unit": {"M411": {"decimals": 0}, "M391": {"decimals": 1}},
                }
            },
        },
        "value": [v for a in areas for v in full[a]],
    }


def test_build_matches_finnish_and_swedish_names_and_country():
    out = facts.build({lang: meta(lang) for lang in facts.LANGS}, dataset(AREAS), MUNICIPALITIES)
    assert set(out["municipalities"]) == {"helsinki", "espoo", "raasepori"}
    assert out["municipalities"]["raasepori"] == {
        "area_code": "KU710",
        "values": {"M391": 61.2, "M411": 27000},
    }
    assert out["country"] == {"M411": 5_650_000, "M391": 5.1}
    pop = out["figures"][0]
    assert pop["code"] == "M411" and pop["label"]["sv"] == "Folkmängd, 2025" and pop["decimals"] == 0
    assert out["figures"][1]["decimals"] == 1
    assert out["source"]["updated"] == "2026-04-13T05:00:00Z"


def test_list_index_and_sparse_values():
    data = dataset(["KU091", "KU049"])
    data["dimension"]["Alue"]["category"]["index"] = ["KU091", "KU049"]
    data["value"] = {"0": 690_000, "3": 6.6}
    rows = facts.parse_jsonstat(data, "Alue", "Tiedot")
    assert rows == {"KU091": {"M411": 690_000, "M391": None}, "KU049": {"M411": None, "M391": 6.6}}


def test_fetch_queries_only_our_areas_and_is_deterministic():
    posted = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        lang = req.url.path.split("/")[4]
        if req.method == "POST":
            body = json.loads(req.content)
            posted.append(body)
            areas = body["query"][0]["selection"]["values"]
            return httpx.Response(200, content=json.dumps(dataset(areas)).encode("utf-8-sig"))
        return httpx.Response(200, json=meta(lang))

    client = PoliteClient(
        UA,
        transport=httpx.MockTransport(handler),
        rate_limiter=RateLimiter(clock=lambda: 0.0, sleep=lambda s: None),
        sleep=lambda s: None,
        allowed_hosts={facts.HOST},
    )
    a = facts.fetch(client, MUNICIPALITIES)
    b = facts.fetch(client, MUNICIPALITIES)
    assert posted[0]["query"][0]["selection"]["values"] == ["KU049", "KU091", "KU710", "SSS"]
    assert posted[0]["response"] == {"format": "json-stat2"}
    assert jsonio.dumps(a) == jsonio.dumps(b)
    assert "fetched" not in jsonio.dumps(a).decode()
