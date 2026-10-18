"""Municipality map file (kunta/mapdata.py) from small hand-made boundaries."""

from __future__ import annotations

import pytest

from kunta import jsonio
from kunta.mapdata import build_map, capabilities_layers, label_point, newest_layer, svg_path


def square(x: int, y: int, size: int = 10_000) -> dict:
    ring = [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]
    return {"type": "Polygon", "coordinates": [ring]}


def feature(code: str, nimi: str, namn: str, geometry: dict) -> dict:
    return {
        "type": "Feature",
        "properties": {"kunta": code, "nimi": nimi, "namn": namn},
        "geometry": geometry,
    }


COUNTRY = {
    "type": "FeatureCollection",
    "features": [
        feature("091", "Helsinki", "Helsingfors", square(380_000, 6_670_000)),
        feature("049", "Espoo", "Esbo", square(370_000, 6_670_000)),
        feature("478", "Maarianhamina - Mariehamn", "Mariehamn", square(100_000, 6_680_000, 2_000)),
        feature(
            "999",
            "Muu",
            "Annan",
            {
                "type": "MultiPolygon",
                "coordinates": [
                    square(390_000, 6_670_000)["coordinates"],
                    square(400_000, 6_675_000, 40)["coordinates"],
                ],
            },
        ),
    ],
}
MUNIS = {
    "helsinki": {"name_fi": "Helsinki", "name_sv": "Helsingfors"},
    "espoo": {"name_fi": "Espoo", "name_sv": "Esbo"},
    "maarianhamina": {"name_fi": "Maarianhamina", "name_sv": "Mariehamn"},
}


def test_newest_layer() -> None:
    xml = (
        "<FeatureType><Name>tilastointialueet:kunta4500k_2024</Name></FeatureType>"
        "<FeatureType><Name>tilastointialueet:kunta4500k_2025</Name></FeatureType>"
        "<FeatureType><Name>tilastointialueet:kunta1000k_2025</Name></FeatureType>"
        "<FeatureType><Name>tilastointialueet:kunta4500k</Name></FeatureType>"
    )
    layers = capabilities_layers(xml)
    assert newest_layer(layers, "4500k") == ("tilastointialueet:kunta4500k_2025", 2025)
    assert newest_layer(layers, "1000k") == ("tilastointialueet:kunta1000k_2025", 2025)


def test_svg_path_relative_and_flipped() -> None:
    d = svg_path(square(380_000, 6_670_000), (370_000, 6_680_000))
    # 100 m units, y grows downwards; the closing point is dropped in favour of z.
    assert d == "M100 100l100 0 0-100-100 0z"


def test_svg_path_rejects_degrees() -> None:
    with pytest.raises(ValueError):
        svg_path(
            {"type": "Polygon", "coordinates": [[[24.9, 60.2], [25, 60.2], [25, 60.3], [24.9, 60.2]]]}, (0, 0)
        )


def test_build_map_matches_ids_and_drops_tiny_islets() -> None:
    data = build_map(COUNTRY, None, MUNIS, year=2025, layers=["a"])
    rows = {r["code"]: r for r in data["municipalities"]}
    assert [r["code"] for r in data["municipalities"]] == ["049", "091", "478", "999"]
    assert rows["091"]["id"] == "helsinki" and rows["478"]["id"] == "maarianhamina"
    assert "id" not in rows["999"]
    assert rows["999"]["d"].count("M") == 1  # the 40 m islet rounds away
    assert data["viewbox"] == [0, 0, 3001, 121]


def test_build_map_fails_on_unmatched_municipality() -> None:
    with pytest.raises(ValueError, match="kauniainen"):
        build_map(COUNTRY, None, {**MUNIS, "kauniainen": {"name_fi": "Kauniainen"}}, year=2025, layers=[])


def test_build_map_deterministic() -> None:
    reversed_country = {**COUNTRY, "features": list(reversed(COUNTRY["features"]))}
    a = jsonio.dumps(build_map(COUNTRY, COUNTRY, MUNIS, year=2025, layers=[]))
    b = jsonio.dumps(build_map(reversed_country, reversed_country, MUNIS, year=2025, layers=[]))
    assert a == b


def test_label_point_avoids_hole() -> None:
    # A 10 km square with a 4 km hole in the middle: the label must not sit in the hole.
    outer = square(380_000, 6_670_000)["coordinates"][0]
    hole = square(383_000, 6_673_000, 4_000)["coordinates"][0]
    x, y = label_point({"type": "Polygon", "coordinates": [outer, hole]})
    assert not (383_000 < x < 387_000 and 6_673_000 < y < 6_677_000)
    assert 380_000 < x < 390_000 and 6_670_000 < y < 6_680_000


def test_inset_rows_have_labels() -> None:
    data = build_map(COUNTRY, COUNTRY, MUNIS, year=2025, layers=[])
    helsinki = next(r for r in data["inset"]["municipalities"] if r["code"] == "091")
    assert helsinki["label"] == [2850, 70]  # the square's centre
    assert "label" not in data["municipalities"][0]
