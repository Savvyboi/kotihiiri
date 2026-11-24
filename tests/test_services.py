"""Finances by service class from the State Treasury (kunta/services.py)."""

import io
import json

import httpx

from kunta import jsonio
from kunta.budget import DATASETS_URL, TAXONOMY_URL
from kunta.http import PoliteClient
from kunta.services import (
    cell_key,
    fetch_services,
    parse_document,
    parse_taxonomy,
    reduce_values,
    stream_rows,
)

TAX_FILE = "https://tkdpprodjrpstacc02.blob.core.windows.net/kuntataloudentaksonomia/KKTPP.json"
DOC = "https://prodkuntarest.westeurope.cloudapp.azure.com/rest/v1/json/dokumentti/lopullinen/KKTPP/0201256-6/2024"


def row(cell, line, code=None, sector="Ulkoiset", part="k-t08", fi="Perusopetus", en=None):
    tag = "fi_met:md103|fi_MC:x1605" + (f"|fi_PA:x{code}" if code else "")
    return {
        "solutunniste": cell,
        "tunnusluku": line,
        "sektori": sector,
        "osakokonaisuus": part,
        "tekstitunniste": tag,
        "palvelu": fi,
        "palvelu_sv": fi,
        "palvelu_en": en or fi,
    }


TAXONOMY = [
    row("1", "Toimintakulut", "3051"),
    row("2", "Toimintakulut", "3051", sector="Sisäiset", en="Basic education"),
    row("3", "Toimintatuotot", "3051"),
    row("4", "Vyörytyskulut", "3051", sector="Sisäiset"),
    row("5", "Toimintakulut", "3051", sector="Kunnat"),  # a sub-sector of Ulkoiset: skipped
    row("6", "Toimintakulut", None, fi="Kaikki palvelu- ja tehtäväluokat"),
    row("7", "Luovutustulot", "3051", part="k-t06"),  # investments: skipped
    row("8", "3005 Myyntituotot, tili", "3051"),  # account detail: skipped
]


def test_cell_keys():
    assert cell_key(TAXONOMY[0]) == ("3051", 0)
    assert cell_key(TAXONOMY[3]) == ("3051", 1)
    assert cell_key(TAXONOMY[5]) == ("ALL", 0)
    assert [cell_key(r) for r in TAXONOMY[4:5] + TAXONOMY[6:]] == [None, None, None]


def test_taxonomy_cells_and_names():
    cells, names = parse_taxonomy(TAXONOMY, keep={"1", "2", "3", "4", "5", "6"})
    assert cells == {"1": ("3051", 0), "2": ("3051", 0), "3": ("3051", 2), "4": ("3051", 1), "6": ("ALL", 0)}
    # The English name comes from the row that has one.
    assert names["3051"] == {"fi": "Perusopetus", "sv": "Perusopetus", "en": "Basic education"}


def test_reduce_sums_lines_per_service():
    cells, _ = parse_taxonomy(TAXONOMY)
    values = {"1": 100.0, "2": 50.0, "3": 20.0, "4": 5.0, "5": 999.0, "6": 300.0, "x": 1.0}
    assert reduce_values(values, cells) == {"ALL": [300.0, 0.0, 0.0, 0.0], "3051": [150.0, 5.0, 20.0, 0.0]}


def test_stream_rows_skips_bom():
    for prefix in (b"\xef\xbb\xbf", b""):
        f = io.BytesIO(prefix + json.dumps(TAXONOMY).encode())
        assert [r["solutunniste"] for r in stream_rows(f)] == [str(i) for i in range(1, 9)]


def test_document_keeps_nonzero_cells():
    rows = [{"tunnusluku": "1", "arvo": "10.50"}, {"tunnusluku": "3", "arvo": "0.00"}, {"arvo": "1"}]
    assert parse_document(rows) == {"1": 10.5}


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
            other = {**rep, "raportointikokonaisuus": "KTAS", "tunnusluvut": "x"}
            return httpx.Response(200, json={"aineistot": [rep, other]})
        if url == DOC:
            return httpx.Response(
                200, json=[{"tunnusluku": "1", "arvo": "10.50"}, {"tunnusluku": "3", "arvo": "2"}]
            )
        return httpx.Response(404)

    client = PoliteClient("test-agent", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    client.rate.interval_s = client.rate.provider_interval_s = 0
    out = tmp_path / "palvelut"
    assert fetch_services(client, {"helsinki": "0201256-6"}, out_dir=out) == {"helsinki": 1}
    [year] = jsonio.read(out / "helsinki.json")["years"]
    assert year["year"] == 2024 and year["approved"] == "2025-05-19 14:37:36"
    assert year["services"] == {"3051": [10.5, 0.0, 2.0, 0.0]}
    assert jsonio.read(out / "services.json")["services"]["3051"]["en"] == "Basic education"
    first = (out / "helsinki.json").read_bytes()
    calls.clear()
    fetch_services(client, {"helsinki": "0201256-6"}, out_dir=out)
    assert DOC not in calls and TAX_FILE not in calls  # nothing new: no report, no taxonomy
    assert (out / "helsinki.json").read_bytes() == first
