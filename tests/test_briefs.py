"""AI briefs (PLAN.md §20): incremental, stored per city and year, robust to messy model answers."""

import json

import httpx
import pytest

from kunta import briefs as b
from kunta import jsonio


def _item(ordinal, title, text="Kaupunginvaltuusto päättää hyväksyä asian.", votes=()):
    return {
        "id": f"helsinki/kaupunginvaltuusto/2026-11-18/{ordinal}",
        "meeting_id": "helsinki/kaupunginvaltuusto/2026-11-18",
        "ordinal": ordinal,
        "title": title,
        "sections": [{"type": "decision", "text": text}, {"type": "history", "text": "ei lähetetä"}],
        "motions": [],
        "votes": list(votes),
        "statements": [],
        "attachments": [],
        "disqualified": [],
        "source_url": "https://example.invalid/",
        "source_ids": {},
        "content_sha256": f"sha{ordinal}-{len(text)}",
        "status": "active",
    }


VOTE = {
    "ordinal": 1,
    "jaa_label": "Esittelijän ehdotus",
    "ei_label": "Vastaehdotus (Meikäläinen)",
    "counts": {"jaa": 50, "ei": 30, "tyhja": 4, "poissa": 1},
    "ballots": [],
    "source": "html",
    "source_url": "https://example.invalid/",
    "needs_review": False,
}


def _meeting(tmp_path, items, stage="minutes", date="2026-11-18"):
    file = {
        "meeting": {
            "id": f"helsinki/kaupunginvaltuusto/{date}",
            "body_id": "helsinki/kaupunginvaltuusto",
            "date": date,
            "stage": stage,
            "source_url": "https://example.invalid/",
            "source_ids": {},
            "attendance": [],
            "items": [i["id"] for i in items],
        },
        "items": items,
    }
    path = tmp_path / "helsinki" / "meetings" / date[:4] / f"kaupunginvaltuusto--{date}.json"
    jsonio.write(path, file)
    jsonio.write(
        tmp_path / "helsinki" / "bodies.json",
        [{"id": "helsinki/kaupunginvaltuusto", "name_fi": "Kaupunginvaltuusto", "kind": "council"}],
    )
    return path


ANSWER = {
    "summary": "Valtuusto hyväksyi hallintosäännön muutoksen. Lisätietoja: matti@example.com.",
    "highlights": ["Hallintosääntö muuttuu 2027", "", "Kaksi", "Kolme", "Neljä", "Viisi"],
    "items": [
        {
            "ordinal": 3,
            "brief": "Hallintosääntöä muutetaan vuoden 2027 alusta.",
            "votes": [{"ordinal": 1, "brief": "Jaa voitti 50–30."}, {"ordinal": 9, "brief": "keksitty"}],
        },
        {"ordinal": 99, "brief": "Asiaa ei ollut kokouksessa."},
    ],
}


class FakeAPI:
    def __init__(self, answers):
        self.answers = list(answers)
        self.sent = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.sent.append(body)
        a = self.answers.pop(0)
        if isinstance(a, httpx.Response):
            return a
        content = a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)
        return httpx.Response(
            200, json={"model": body["model"], "choices": [{"message": {"content": content}}]}
        )


def _client(api):
    return b.OpenRouter(
        "key", models=("m1:free", "m2:free"), sleep=lambda s: None, transport=httpx.MockTransport(api)
    )


def test_procedural_items_are_not_sent():
    assert b.is_procedural("Kokouksen laillisuus ja päätösvaltaisuus")
    assert b.is_procedural("Pöytäkirjan tarkastajien valinta")
    assert b.is_procedural("Salassa pidettävä (JulkL 24.1 §)")
    assert not b.is_procedural("Hallintosäännön muuttaminen")


def test_parse_json_tolerates_thinking_and_fences():
    raw = '<think>hmm {"x":1}</think>\nTässä:\n```json\n{"summary": "ok", "items": []}\n```'
    assert b.parse_json(raw) == {"summary": "ok", "items": []}
    with pytest.raises(ValueError):
        b.parse_json("en osaa")


def test_run_writes_one_file_per_year_and_is_incremental(tmp_path):
    items = [
        _item(1, "Kokouksen laillisuus ja päätösvaltaisuus"),
        _item(3, "Hallintosäännön muuttaminen", votes=[VOTE]),
    ]
    path = _meeting(tmp_path, items)
    api = FakeAPI([ANSWER])
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path)
    assert report.written == 1 and report.requests == 1

    prompt = api.sent[0]["messages"][1]["content"]
    assert "Hallintosäännön muuttaminen" in prompt
    assert "laillisuus" not in prompt  # procedural item left out
    assert "ei lähetetä" not in prompt  # history sections left out
    assert api.sent[0]["models"] == ["m1:free", "m2:free"]

    stored = jsonio.read(tmp_path / "helsinki" / "briefs" / "2026.json")
    entry = stored["helsinki/kaupunginvaltuusto/2026-11-18"]
    assert "@" not in entry["summary"]  # PII stripped from model output
    assert entry["highlights"] == ["Hallintosääntö muuttuu 2027", "Kaksi", "Kolme", "Neljä"]
    assert set(entry["items"]) == {"3"}  # invented ordinal 99 dropped
    assert entry["items"]["3"]["votes"] == {"1": "Jaa voitti 50–30."}  # invented vote 9 dropped
    assert entry["items"]["3"]["sha"] == items[1]["content_sha256"]
    assert entry["model"] == "m1:free" and entry["stage"] == "minutes"

    # Nothing changed: nothing sent, file untouched.
    before = (tmp_path / "helsinki" / "briefs" / "2026.json").read_bytes()
    api2 = FakeAPI([])
    assert b.run(["helsinki"], _client(api2), data_dir=tmp_path).requests == 0
    assert (tmp_path / "helsinki" / "briefs" / "2026.json").read_bytes() == before

    # The item's text changed: the meeting is briefed again.
    file = jsonio.read(path)
    file["items"][1]["content_sha256"] = "changed"
    jsonio.write(path, file)
    api3 = FakeAPI([ANSWER])
    assert b.run(["helsinki"], _client(api3), data_dir=tmp_path).written == 1


def test_agendas_are_skipped_unless_asked(tmp_path):
    _meeting(tmp_path, [_item(3, "Hallintosäännön muuttaminen")], stage="agenda")
    assert b.find_pending(["helsinki"], tmp_path) == []
    assert len(b.find_pending(["helsinki"], tmp_path, agendas=True)) == 1


def test_daily_limit_stops_the_run_and_keeps_progress(tmp_path):
    _meeting(tmp_path, [_item(3, "Hallintosäännön muuttaminen")], date="2026-11-18")
    _meeting(tmp_path, [_item(3, "Talousarvio 2027")], date="2026-11-04")
    limit = httpx.Response(429, text='{"error":{"message":"Rate limit exceeded: free-models-per-day"}}')
    api = FakeAPI([ANSWER, limit])
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path)
    assert report.written == 1 and report.pending == 1 and "daily limit" in report.stopped
    assert "helsinki/kaupunginvaltuusto/2026-11-18" in jsonio.read(
        tmp_path / "helsinki" / "briefs" / "2026.json"
    )


def test_request_budget_is_respected(tmp_path):
    _meeting(tmp_path, [_item(3, "A")], date="2026-11-18")
    _meeting(tmp_path, [_item(3, "B")], date="2026-11-04")
    api = FakeAPI([ANSWER])
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path, max_requests=1)
    assert report.written == 1 and report.requests == 1 and report.pending == 1


def test_bad_json_is_retried_once_then_skipped(tmp_path):
    _meeting(tmp_path, [_item(3, "Hallintosäännön muuttaminen")])
    api = FakeAPI(["Valitettavasti en voi", "edelleen proosaa"])
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path)
    assert report.written == 0 and report.failed == ["helsinki/kaupunginvaltuusto/2026-11-18"]
    assert not (tmp_path / "helsinki" / "briefs").exists()


def test_long_meetings_are_split_and_summarised_from_item_briefs(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "CHUNK_CHARS", 200)
    items = [_item(n, f"Asia {n}", text="Pitkä teksti. " * 20) for n in (3, 4)]
    _meeting(tmp_path, items)
    a1 = {"summary": "", "highlights": [], "items": [{"ordinal": 3, "brief": "Kolmas."}]}
    a2 = {"summary": "", "highlights": [], "items": [{"ordinal": 4, "brief": "Neljäs."}]}
    final = {"summary": "Kaksi asiaa.", "highlights": ["Kolmas", "Neljäs"]}
    api = FakeAPI([a1, a2, final])
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path)
    assert report.requests == 3
    entry = b.load_briefs("helsinki", tmp_path)["helsinki/kaupunginvaltuusto/2026-11-18"]
    assert entry["summary"] == "Kaksi asiaa." and set(entry["items"]) == {"3", "4"}
    assert "Asia 3: Kolmas." in api.sent[2]["messages"][1]["content"]


def test_briefs_of_removed_meetings_are_pruned(tmp_path):
    path = _meeting(tmp_path, [_item(3, "Hallintosäännön muuttaminen")])
    b.run(["helsinki"], _client(FakeAPI([ANSWER])), data_dir=tmp_path)
    path.unlink()
    _meeting(tmp_path, [_item(3, "Muu asia")], date="2026-11-04")
    b.run(["helsinki"], _client(FakeAPI([ANSWER])), data_dir=tmp_path)
    assert list(b.load_briefs("helsinki", tmp_path)) == ["helsinki/kaupunginvaltuusto/2026-11-04"]


def _digest_answer(n_meetings=2):
    return {
        "summary": "Valtuusto päätti hallintosäännöstä ja talousarviosta.",
        "points": [
            {"text": "Hallintosääntö muuttuu.", "meeting": 2},
            {"text": "Ilman lähdettä."},
            {"text": "Väärä numero.", "meeting": 99},
            {"text": ""},
        ],
    }


def test_city_digest_from_meeting_briefs(tmp_path):
    _meeting(tmp_path, [_item(3, "Talousarvio 2027")], date="2026-11-04")
    _meeting(tmp_path, [_item(3, "Hallintosäännön muuttaminen")], date="2026-11-18")
    _meeting(tmp_path, [_item(3, "Vanha asia")], date="2026-09-01")  # outside the 30-day window
    api = FakeAPI([ANSWER, ANSWER, ANSWER, _digest_answer()])
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path)
    assert report.written == 3 and report.digests == 1 and report.requests == 4

    prompt = api.sent[3]["messages"][1]["content"]
    assert "2026-10-19–2026-11-18" in prompt and "2026-09-01" not in prompt
    d = jsonio.read(b.digest_path("helsinki", tmp_path))
    assert d["period_start"] == "2026-10-19" and d["period_end"] == "2026-11-18"
    assert d["points"][0] == {
        "text": "Hallintosääntö muuttuu.",
        "meeting_id": "helsinki/kaupunginvaltuusto/2026-11-18",
    }
    assert d["points"][1:] == [{"text": "Ilman lähdettä."}, {"text": "Väärä numero."}]
    assert d["meetings"] == [
        "helsinki/kaupunginvaltuusto/2026-11-04",
        "helsinki/kaupunginvaltuusto/2026-11-18",
    ]
    # digest.json is not mistaken for a year of meeting briefs
    assert "input_sha256" not in b.load_briefs("helsinki", tmp_path)

    # Nothing new: no requests. A new meeting in the window: the digest is redone.
    assert b.run(["helsinki"], _client(FakeAPI([])), data_dir=tmp_path).requests == 0
    _meeting(tmp_path, [_item(3, "Uusi asia")], date="2026-11-25")
    api = FakeAPI([ANSWER, _digest_answer()])
    assert b.run(["helsinki"], _client(api), data_dir=tmp_path).digests == 1


def test_digest_needs_two_meetings_and_keeps_budget_for_it(tmp_path):
    _meeting(tmp_path, [_item(3, "A")], date="2026-11-18")
    api = FakeAPI([ANSWER])
    assert b.run(["helsinki"], _client(api), data_dir=tmp_path).digests == 0
    assert not b.digest_path("helsinki", tmp_path).exists()

    # Backlog of 4 meetings, budget 4: one request is held back for the digest.
    for d in ("2026-11-04", "2026-11-11", "2026-11-12", "2026-11-13"):
        _meeting(tmp_path, [_item(3, "B")], date=d)
    api = FakeAPI([ANSWER, ANSWER, ANSWER, _digest_answer()])
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path, max_requests=4)
    assert report.written == 3 and report.digests == 1 and report.pending == 1


def test_only_free_models_are_accepted():
    with pytest.raises(b.ModelError):
        b.OpenRouter("key", models=("nvidia/nemotron-3.5-super-vl",))
    with pytest.raises(b.ModelError):
        b.OpenRouter("key", models=())
    assert b.DEFAULT_MODELS == ("nvidia/nemotron-3.5-super-vl:free",)


def test_summaries_keep_paragraphs_items_stay_one_line():
    text = "Ensimmäinen kappale.\n\n\nToinen   kappale.\nSama kappale."
    assert b.clean(text, 1000, paragraphs=True) == "Ensimmäinen kappale.\n\nToinen kappale. Sama kappale."
    assert "\n" not in b.clean(text, 1000)
