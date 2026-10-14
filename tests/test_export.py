import csv
import io
import zipfile

import pyarrow.parquet as pq

from kunta import jsonio
from kunta.export import TABLES, collect, write


def _data(root):
    jsonio.write(
        root / "espoo/bodies.json", [{"id": "espoo/valtuusto", "name_fi": "Valtuusto", "kind": "council"}]
    )
    vote = {
        "ordinal": 1,
        "jaa_label": "Esitys",
        "ei_label": "Muutos",
        "counts": {"jaa": 1, "ei": 1, "tyhja": 0, "poissa": 0},
        "ballots": [
            {"person_ref": {"raw": "Virtanen Matti"}, "choice": "jaa", "group_text": "KOK"},
            {"person_ref": {"raw": "Korhonen Anna"}, "choice": "ei"},
        ],
        "source": "pdf",
        "source_url": "https://example.test/v.pdf",
    }
    item = {
        "id": "espoo/valtuusto/2025-09-15/1",
        "meeting_id": "espoo/valtuusto/2025-09-15",
        "ordinal": 1,
        "pykala": 1,
        "title": "Kaava, Sala Mies",
        "sections": [{"type": "decision", "text": "Hyväksyttiin. Sala Mies"}],
        "motions": [{"kind": "counter_proposal", "proposer_ref": {"raw": "Korhonen Anna"}, "text": "Muutos"}],
        "votes": [vote],
        "source_url": "https://example.test/1",
    }
    hidden = dict(item, id="espoo/valtuusto/2025-09-15/2", ordinal=2, title="Poistettu")
    meeting = {
        "id": "espoo/valtuusto/2025-09-15",
        "body_id": "espoo/valtuusto",
        "date": "2025-09-15",
        "stage": "minutes",
        "source_url": "https://example.test/m",
        "attendance": [
            {"person_ref": {"raw": "Virtanen Matti"}, "role_text": "valtuutettu", "present": True}
        ],
        "items": [item["id"], hidden["id"]],
    }
    jsonio.write(
        root / "espoo/meetings/2025/valtuusto--2025-09-15.json", {"meeting": meeting, "items": [item, hidden]}
    )
    jsonio.write(
        root / "espoo/people.json",
        {
            "persons": [{"id": "espoo/virtanen-matti", "city": "espoo", "name": "Matti Virtanen",
                         "sort_name": "Virtanen Matti", "aliases": [], "party": "KOK"}],
            "memberships": [{"person_id": "espoo/virtanen-matti", "body_id": "espoo/valtuusto",
                             "role": "member", "source": "attendance"}],
        },
    )  # fmt: skip


def test_export_tables_with_takedowns(tmp_path):
    _data(tmp_path / "data")
    rows = collect(["espoo"], tmp_path / "data", ({"espoo/valtuusto/2025-09-15/2"}, ["Sala Mies"]))
    assert [r["id"] for r in rows["items"]] == ["espoo/valtuusto/2025-09-15/1"]  # the taken-down item is gone
    assert rows["items"][0]["title"] == "Kaava, [poistettu]"
    assert rows["items"][0]["decision"] == "Hyväksyttiin. [poistettu]"
    assert rows["meetings"][0]["item_count"] == 1
    assert [(b["vote_id"], b["name"], b["group"]) for b in rows["ballots"]] == [
        ("espoo/valtuusto/2025-09-15/1/1", "Virtanen Matti", "KOK"),
        ("espoo/valtuusto/2025-09-15/1/1", "Korhonen Anna", None),
    ]

    out = tmp_path / "exports"
    manifest = write(rows, out)
    assert manifest["tables"]["votes"]["rows"] == 1
    votes = list(csv.DictReader(io.StringIO((out / "votes.csv").read_text(encoding="utf-8"))))
    assert (votes[0]["jaa"], votes[0]["ei"], votes[0]["needs_review"]) == ("1", "1", "False")
    assert pq.read_table(out / "persons.parquet").to_pylist()[0]["party"] == "KOK"
    with zipfile.ZipFile(out / "all.zip") as zf:
        assert sorted(zf.namelist()) == sorted(["README.txt", *(f"{t}.csv" for t in TABLES)])

    # deterministic: a second export writes the same bytes
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    write(collect(["espoo"], tmp_path / "data", ({"espoo/valtuusto/2025-09-15/2"}, ["Sala Mies"])), out)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == first
