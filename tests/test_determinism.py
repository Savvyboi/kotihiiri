import datetime as dt

from kunta import jsonio
from kunta.ids import body_id, item_id, meeting_file_path, meeting_id, person_id, slugify
from kunta.models import AgendaItem, Meeting, MeetingFile


def sample():
    m = Meeting(
        id="helsinki/kaupunginvaltuusto/2026-09-23",
        body_id="helsinki/kaupunginvaltuusto",
        date=dt.date(2026, 9, 23),
        stage="minutes",
        source_url="https://x/1",
        items=["helsinki/kaupunginvaltuusto/2026-09-23/1"],
    )
    it = AgendaItem(
        id=m.items[0],
        meeting_id=m.id,
        ordinal=1,
        title="Päätös",
        source_url="https://x/2",
        content_sha256="0" * 64,
    )
    return MeetingFile(meeting=m, items=[it])


def test_byte_identical(tmp_path):
    a = jsonio.dumps(sample())
    b = jsonio.dumps(MeetingFile.model_validate(jsonio.read(_w(tmp_path, sample()))))
    assert a == b
    assert a.endswith(b"\n")


def _w(tmp_path, v):
    p = tmp_path / "x.json"
    jsonio.write(p, v)
    return p


def test_no_rewrite_when_unchanged(tmp_path):
    p = tmp_path / "m.json"
    assert jsonio.write(p, sample()) is True
    assert jsonio.write(p, sample()) is False


def test_sorted_keys_and_nfc():
    decomposed = "Päätös"
    out = jsonio.dumps({"b": decomposed, "a": 1})
    assert out.index(b'"a"') < out.index(b'"b"')
    assert "Päätös".encode() in out


def test_ids():
    assert slugify("Kaupunkiympäristölautakunta") == "kaupunkiymparistolautakunta"
    assert slugify("Nämnden Svenska rum") == "namnden-svenska-rum"
    b = body_id("helsinki", "Kaupunkiympäristölautakunta")
    assert b == "helsinki/kaupunkiymparistolautakunta"
    m = meeting_id(b, dt.date(2025, 3, 4))
    assert m == "helsinki/kaupunkiymparistolautakunta/2025-03-04"
    assert meeting_id(b, dt.date(2025, 3, 4), 2).endswith("-2")
    assert item_id(m, 3) == m + "/3"
    assert meeting_file_path(m) == "helsinki/meetings/2025/kaupunkiymparistolautakunta--2025-03-04.json"
    assert person_id("espoo", "Mäkinen", "Juha") == "espoo/makinen-juha"
    assert person_id("espoo", "Mäkinen", "Juha", {"espoo/makinen-juha"}) == "espoo/makinen-juha-2"
