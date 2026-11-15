"""Finances by service class from the State Treasury (kunta/services.py)."""

import io
import json

import httpx

from kunta import jsonio
from kunta.budget import DATASETS_URL, TAXONOMY_URL
from kunta.http import PoliteClient
from kunta.services import fetch_services, parse_document, parse_taxonomy, stream_rows

TAX_FILE = "https://tkdpprodjrpstacc02.blob.core.windows.net/kuntataloudentaksonomia/KKTPP.json"
DOC = "https://prodkuntarest.westeurope.cloudapp.azure.com/rest/v1/json/dokumentti/lopullinen/KKTPP/0201256-6/2024"
TAXONOMY = [
    {
        "solutunniste": "3499809",
        "tunnusluku": "Toimintakulut",
        "tehtava": "Perusopetus",
        "taso": 2,
        "osakokonaisuus": "k-t08",
    },
    {
        "solutunniste": "2102827",
        "tunnusluku": " Toimintatuotot ",
        "tehtava": "Kirjastot",
        "taso": None,
        "osakokonaisuus": "k-t08",
    },
    {"solutunniste": "62", "tunnusluku": "Y-tunnus", "osakokonaisuus": "t00"},
]


def test_taxonomy_keeps_labels():
    cells = parse_taxonomy(TAXONOMY)
    assert set(cells) == {"3499809", "2102827"}
    assert cells["3499809"] == {
        "osakokonaisuus": "k-t08",
        "taso": 2,
        "tehtava": "Perusopetus",
        "tunnusluku": "Toimintakulut",
    }
    assert cells["2102827"]["tunnusluku"] == "Toimintatuotot" and "taso" not in cells["2102827"]


def test_stream_rows_skips_bom():
    for prefix in (b"\xef\xbb\xbf", b""):
        f = io.BytesIO(prefix + json.dumps(TAXONOMY).encode())
        assert [r["solutunniste"] for r in stream_rows(f)] == ["3499809", "2102827", "62"]


def test_document_keeps_nonzero_cells():
    rows = [
        {"tunnusluku": "3499809", "arvo": "2112093.86"},
        {"tunnusluku": "2102827", "arvo": "0.00"},
        {"tunnusluku": "999", "arvo": "5.00"},
    ]
    assert parse_document(rows) == {"3499809": 2112093.86, "999": 5.0}
    assert set(parse_taxonomy(TAXONOMY, keep={"999", "3499809"})) == {"3499809"}


def test_fetch_writes_and_skips_unchanged(tmp_path):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.endswith("/robots.txt"):
            return httpx.Response(404)
        if url == TAXONOMY_URL:
            return httpx.Response(200, json=[TAX_FILE.replace("KKTPP", "KTAS"), TAX_FILE])
        if url == TAX_FILE:
            return httpx.Response(200, content=b"\xef\xbb\xbf" + json.dumps(TAXONOMY).encode())
        if url == DATASETS_URL:
            rep = {
                "ytunnus": "0201256-6",
                "raportointikokonaisuus": "KKTPP",
                "raportointikausi": "2024",
                "hyvaksymisvaihe": "Lopullinen",
                "hyvaksymispvm": "2025-05-19 14:37:36.067",
                "tunnusluvut": DOC,
            }
            return httpx.Response(
                200, json={"aineistot": [rep, {**rep, "raportointikokonaisuus": "KTAS", "tunnusluvut": "x"}]}
            )
        if url == DOC:
            return httpx.Response(200, json=[{"tunnusluku": "3499809", "arvo": "10.50"}])
        return httpx.Response(404)

    client = PoliteClient("test-agent", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    client.rate.interval_s = client.rate.provider_interval_s = 0
    out = tmp_path / "palvelut"
    assert fetch_services(client, {"helsinki": "0201256-6"}, out_dir=out) == {"helsinki": 1}
    data = jsonio.read(out / "helsinki.json")
    assert data["years"] == [
        {
            "year": 2024,
            "stage": "Lopullinen",
            "approved": "2025-05-19 14:37:36",
            "source_url": DOC,
            "values": {"3499809": 10.5},
        }
    ]
    assert jsonio.read(out / "items.json")["cells"]["3499809"]["tehtava"] == "Perusopetus"
    first = (out / "helsinki.json").read_bytes()
    calls.clear()
    fetch_services(client, {"helsinki": "0201256-6"}, out_dir=out)
    assert DOC not in calls
    assert (out / "helsinki.json").read_bytes() == first
