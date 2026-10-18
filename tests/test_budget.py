"""Budgets from the State Treasury API (kunta/budget.py): taxonomy, report choice, cell mapping."""

import json

import httpx

from kunta import jsonio
from kunta.budget import (
    DATASETS_URL,
    TAXONOMY_URL,
    fetch_budgets,
    latest_reports,
    parse_document,
    parse_taxonomy,
)
from kunta.http import PoliteClient

TAX_FILE = "https://tkdpprodjrpstacc02.blob.core.windows.net/kuntataloudentaksonomia/KTAS.json"
DOC = "https://prodkuntarest.westeurope.cloudapp.azure.com/rest/v1/json/dokumentti/lopullinen/KTAS/0101263-6/2026"


def tax_row(cell, label, order, column, level=1, sv=None, en=None, part="k-t05"):
    names = {
        1: "Laadintakauden talousarvio 202x-1",
        2: "Talousarvio 202x",
        3: "Taloussuunnitelma 202x+1",
        4: "Taloussuunnitelma 202x+2",
    }
    return {
        "solutunniste": cell,
        "taso": level,
        "tunnusluku": label,
        "tunnusluku_sv": sv,
        "tunnusluku_en": en,
        "tehtava": names.get(column),
        "tehtava_jarjestys": column,
        "tunnusluku_jarjestys": order,
        "osakokonaisuus": part,
    }


TAXONOMY = [
    tax_row("16", "Toimintatulot", 2, 2, sv="Verksamhetsintäkter", en="Operating income"),
    tax_row("1715", "Toimintatulot", 2, 1, sv="Verksamhetsintäkter", en="Operating income"),
    tax_row("805", "Toimintatulot", 2, 3),
    tax_row("769", "Toimintatulot", 2, 4),
    tax_row("473", "   Henkilöstömenot", 10, 2, level=2),
    tax_row("1906", "Tuloveroprosentti", 41, 2),
    tax_row("62", "Y-tunnus", 1, 1, part="t00"),
    {
        "solutunniste": "k-t05_R0010",
        "taso": 0,
        "tunnusluku": None,
        "tehtava_jarjestys": None,
        "osakokonaisuus": "k-t05",
    },
]


def doc_row(cell, value, note=""):
    return {"tunnusluku": cell, "arvo": value, "kommentti": note, "osakokonaisuus": "k-t05"}


def test_taxonomy_lines_and_cells():
    lines, cells = parse_taxonomy(TAXONOMY)
    assert [x.key for x in lines] == ["toimintatulot", "henkilostomenot", "tuloveroprosentti"]
    assert lines[0].sv == "Verksamhetsintäkter" and lines[0].en == "Operating income"
    assert lines[1].fi == "Henkilöstömenot" and lines[1].level == 2
    # Lines without a Swedish or English label fall back to Finnish.
    assert lines[2].en == "Tuloveroprosentti"
    assert cells["16"].column == "budget" and cells["1715"].column == "prev"
    assert cells["805"].column == "plan1" and cells["769"].column == "plan2"
    assert "62" not in cells  # report metadata is not a figure


def test_document_values_and_notes():
    _, cells = parse_taxonomy(TAXONOMY)
    values, notes = parse_document(
        [
            doc_row("16", "163701319.00", "Kasvu johtuu maksuista. Lisätietoja: talous@espoo.fi"),
            doc_row("1715", "150000000.5"),
            doc_row("1906", "5.36"),
            doc_row("999999", "1.00"),  # not in the taxonomy
            doc_row("473", "not a number"),
        ],
        cells,
    )
    assert values == {
        "toimintatulot": {"budget": 163701319.0, "prev": 150000000.5},
        "tuloveroprosentti": {"budget": 5.36},
    }
    assert notes == {"toimintatulot": "Kasvu johtuu maksuista. Lisätietoja: [poistettu]"}


def test_latest_report_per_year():
    rows = [
        {
            "ytunnus": "1",
            "raportointikokonaisuus": "KTAS",
            "raportointikausi": "2026",
            "hyvaksymisvaihe": "Lopullinen",
            "hyvaksymispvm": "2026-01-10",
            "tunnusluvut": "a",
        },
        {
            "ytunnus": "1",
            "raportointikokonaisuus": "KTAS",
            "raportointikausi": "2026",
            "hyvaksymisvaihe": "Jälkikorjattu",
            "hyvaksymispvm": "2026-02-01",
            "tunnusluvut": "b",
        },
        {
            "ytunnus": "1",
            "raportointikokonaisuus": "KTAS",
            "raportointikausi": "2025",
            "hyvaksymisvaihe": "Lopullinen",
            "hyvaksymispvm": "2025-01-10",
            "tunnusluvut": "c",
        },
        {
            "ytunnus": "1",
            "raportointikokonaisuus": "KTAS",
            "raportointikausi": "2019",
            "hyvaksymisvaihe": "Lopullinen",
            "hyvaksymispvm": "2019-01-10",
            "tunnusluvut": "old",
        },
        {
            "ytunnus": "1",
            "raportointikokonaisuus": "KKNR",
            "raportointikausi": "2026C06",
            "hyvaksymisvaihe": "Lopullinen",
            "hyvaksymispvm": "2026-07-10",
            "tunnusluvut": "q",
        },
        {
            "ytunnus": "2",
            "raportointikokonaisuus": "KTAS",
            "raportointikausi": "2026",
            "hyvaksymisvaihe": "Lopullinen",
            "hyvaksymispvm": "2026-01-10",
            "tunnusluvut": "other",
        },
    ]
    best = latest_reports(rows, {"1"})
    assert sorted(best) == [("1", 2025), ("1", 2026)]
    assert best[("1", 2026)]["tunnusluvut"] == "b"


def _transport(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.endswith("/robots.txt"):
            return httpx.Response(404)
        if url == TAXONOMY_URL:
            return httpx.Response(200, json=[TAX_FILE.replace("KTAS", "KKNR"), TAX_FILE])
        if url == TAX_FILE:
            # The blob files start with a byte-order mark.
            return httpx.Response(200, content=b"\xef\xbb\xbf" + json.dumps(TAXONOMY).encode())
        if url == DATASETS_URL:
            return httpx.Response(
                200,
                json={
                    "aineistot": [
                        {
                            "ytunnus": "0101263-6",
                            "raportointikokonaisuus": "KTAS",
                            "raportointikausi": "2026",
                            "hyvaksymisvaihe": "Lopullinen",
                            "hyvaksymispvm": "2026-01-14 10:22:27.52",
                            "tunnusluvut": DOC,
                        }
                    ]
                },
            )
        if url == DOC:
            return httpx.Response(200, json=[doc_row("16", "100.00"), doc_row("1906", "5.36")])
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_fetch_writes_files_and_skips_unchanged(tmp_path):
    calls: list[str] = []
    client = PoliteClient("test-agent", transport=_transport(calls), sleep=lambda s: None)
    client.rate.interval_s = client.rate.provider_interval_s = 0
    out = tmp_path / "talous"
    summary = fetch_budgets(client, ["espoo", "nowhere"], out_dir=out, business_ids={"espoo": "0101263-6"})
    assert summary == {"espoo": 1}
    data = jsonio.read(out / "espoo.json")
    assert data["business_id"] == "0101263-6"
    [year] = data["years"]
    assert year["year"] == 2026 and year["approved"] == "2026-01-14 10:22:27"
    assert year["values"] == {"toimintatulot": {"budget": 100.0}, "tuloveroprosentti": {"budget": 5.36}}
    items = jsonio.read(out / "items.json")
    assert [x["key"] for x in items["lines"]] == ["toimintatulot", "henkilostomenot", "tuloveroprosentti"]
    first = (out / "espoo.json").read_bytes()

    calls.clear()
    fetch_budgets(client, ["espoo"], out_dir=out, business_ids={"espoo": "0101263-6"})
    assert DOC not in calls  # same approval time: the stored year is kept
    assert (out / "espoo.json").read_bytes() == first
