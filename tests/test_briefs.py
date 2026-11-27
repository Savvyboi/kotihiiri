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
    "summary": {
        "fi": "Valtuusto hyväksyi hallintosäännön muutoksen. Lisätietoja: matti@example.com.",
        "sv": "Fullmäktige godkände ändringen av förvaltningsstadgan.",
        "en": "The council approved the change to the administrative rules.",
        "de": "Nicht gefragt.",
    },
    "highlights": {
        "fi": ["Hallintosääntö muuttuu 2027", "", "Kaksi", "Kolme", "Neljä", "Viisi"],
        "sv": ["Förvaltningsstadgan ändras 2027"],
        "en": ["Administrative rules change in 2027"],
    },
    "items": [
        {
            "ordinal": 3,
            "brief": {
                "fi": "Hallintosääntöä muutetaan vuoden 2027 alusta.",
                "sv": "Förvaltningsstadgan ändras från början av 2027.",
                "en": "The administrative rules change from the start of 2027.",
            },
            "votes": [
                {"ordinal": 1, "brief": {"fi": "Jaa voitti 50–30.", "sv": "Ja vann 50–30.", "en": ""}},
                {"ordinal": 9, "brief": {"fi": "keksitty"}},
            ],
        },
        {"ordinal": 99, "brief": {"fi": "Asiaa ei ollut kokouksessa."}},
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
    assert set(entry["summary"]) == {"fi", "sv", "en"}  # only the site's three languages
    assert "@" not in entry["summary"]["fi"]  # PII stripped from model output
    assert entry["highlights"]["fi"] == ["Hallintosääntö muuttuu 2027", "Kaksi", "Kolme", "Neljä"]
    assert entry["highlights"]["en"] == ["Administrative rules change in 2027"]
    assert set(entry["items"]) == {"3"}  # invented ordinal 99 dropped
    assert entry["items"]["3"]["brief"]["sv"] == "Förvaltningsstadgan ändras från början av 2027."
    # invented vote 9 dropped; an empty translation is left out (the site falls back to Finnish)
    assert entry["items"]["3"]["votes"] == {"1": {"fi": "Jaa voitti 50–30.", "sv": "Ja vann 50–30."}}
    assert entry["lang"] == "fi"
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
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path, workers=1)
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
    # A bare string (no language map) is taken to be in the source language.
    a1 = {"items": [{"ordinal": 3, "brief": "Kolmas."}]}
    a2 = {"items": [{"ordinal": 4, "brief": {"fi": "Neljäs.", "en": "Fourth."}}]}
    final = {"summary": {"fi": "Kaksi asiaa.", "sv": "Två ärenden."}, "highlights": {"fi": ["Kolmas"]}}
    api = FakeAPI([a1, a2, final])
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path)
    assert report.requests == 3
    entry = b.load_briefs("helsinki", tmp_path)["helsinki/kaupunginvaltuusto/2026-11-18"]
    assert entry["summary"] == {"fi": "Kaksi asiaa.", "sv": "Två ärenden."}
    assert entry["items"]["3"]["brief"] == {"fi": "Kolmas."}
    assert entry["items"]["4"]["brief"] == {"fi": "Neljäs.", "en": "Fourth."}
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
        "summary": {
            "fi": "Valtuusto päätti hallintosäännöstä ja talousarviosta.",
            "sv": "Fullmäktige beslöt om förvaltningsstadgan och budgeten.",
            "en": "The council decided on the administrative rules and the budget.",
        },
        "points": [
            {"text": {"fi": "Hallintosääntö muuttuu.", "en": "Rules change."}, "meeting": 2},
            {"text": {"fi": "Ilman lähdettä."}},
            {"text": {"fi": "Väärä numero."}, "meeting": 99},
            {"text": {"fi": ""}},
            {"text": {"en": "Only English."}},
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
    assert d["summary"]["sv"].startswith("Fullmäktige")
    assert d["points"][0] == {
        "text": {"fi": "Hallintosääntö muuttuu.", "en": "Rules change."},
        "meeting_id": "helsinki/kaupunginvaltuusto/2026-11-18",
    }
    # a point without the source language is dropped
    assert d["points"][1:] == [{"text": {"fi": "Ilman lähdettä."}}, {"text": {"fi": "Väärä numero."}}]
    assert "Valtuusto hyväksyi hallintosäännön muutoksen." in prompt  # Finnish summaries read
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
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path, max_requests=4, workers=1)
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


def _words(n):
    return " ".join(["sana"] * n)


def test_short_summary_is_asked_for_once_more_and_the_longer_kept(tmp_path):
    _meeting(tmp_path, [_item(3, "A"), _item(4, "B")])
    short = {"summary": {"fi": _words(40)}, "items": [{"ordinal": 3, "brief": {"fi": "Kolmas."}}]}
    longer = {"summary": {"fi": _words(90), "sv": "ord"}, "highlights": {"fi": ["Nosto"]}, "items": []}
    api = FakeAPI([short, longer])
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path)
    assert report.written == 1 and report.requests == 2
    assert "oli vain 40 sanaa" in api.sent[1]["messages"][1]["content"]
    entry = b.load_briefs("helsinki", tmp_path)["helsinki/kaupunginvaltuusto/2026-11-18"]
    assert b.words(entry["summary"]["fi"]) == 90 and entry["highlights"] == {"fi": ["Nosto"]}
    assert set(entry["items"]) == {"3"}  # item briefs come from the first answer

    # A one-item meeting is not padded out.
    _meeting(tmp_path, [_item(3, "C")], date="2026-11-04")
    api = FakeAPI([short, _digest_answer()])
    assert b.run(["helsinki"], _client(api), data_dir=tmp_path).requests == 2  # meeting + digest
    assert "oli vain" not in api.sent[1]["messages"][1]["content"]


def test_prompt_asks_for_three_languages_names_and_who_decided(tmp_path):
    _meeting(tmp_path, [_item(3, "A")])
    api = FakeAPI([ANSWER])
    b.run(["helsinki"], _client(api), data_dir=tmp_path)
    system, user = (m["content"] for m in api.sent[0]["messages"])
    assert "yksi yhtiö" in system and "esitti" in system and "kolmella kielellä" in system
    assert '"sv"' in user and '"en"' in user and api.sent[0]["max_tokens"] >= 16000


def test_meetings_run_in_parallel_within_the_budget(tmp_path):
    for d in ("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09"):
        _meeting(tmp_path, [_item(3, "A")], date=d)
    api = FakeAPI([ANSWER] * 5)
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path, max_requests=5, workers=3)
    # 6 meetings, 5 requests, one held back for the digest: 4 meetings, then the digest
    # nothing more.
    assert report.requests <= 5 and report.written == 4 and report.pending == 2
    assert len(b.load_briefs("helsinki", tmp_path)) == 4


@pytest.mark.parametrize(
    "title",
    [
        "Kokouksen laillisuuden ja päätösvaltaisuuden toteaminen sekä pöytäkirjan tarkastajien valinta",
        "Laillisuuden ja päätösvaltaisuuden toteaminen",
        "Konsernijaoston pöytäkirjan tarkastaminen",
        "Asioiden käsittelyjärjestys",
    ],
)
def test_opening_formalities_in_other_case_forms_are_procedural(title):
    # Helsinki and Espoo (527 and 317 meetings) and Vantaa's konsernijaosto (2026-11-27 trial)
    assert b.is_procedural(title)


def test_substantive_titles_are_not_procedural():
    for title in ("Valtuuston työjärjestyksen muuttaminen", "Helsinki Partners Oy:n omistajastrategia"):
        assert not b.is_procedural(title)


def test_a_cut_answer_is_split_down_and_summarised_from_items(tmp_path):
    _meeting(tmp_path, [_item(3, "A"), _item(4, "B")])
    cut = '{"summary": {"fi": "Kesken'
    a3 = {"items": [{"ordinal": 3, "brief": {"fi": "Kolmas.", "sv": "Tredje.", "en": "Third."}}]}
    final = {"summary": {"fi": "Kaksi asiaa.", "en": "Two items."}, "highlights": {"fi": ["Kolmas"]}}
    # both items cut short, then item 3 alone, item 4 alone (cut twice), then the summary
    api = FakeAPI([cut, a3, "proosaa", "edelleen proosaa", final])
    report = b.run(["helsinki"], _client(api), data_dir=tmp_path)
    assert report.written == 1 and report.requests == 5
    entry = b.load_briefs("helsinki", tmp_path)["helsinki/kaupunginvaltuusto/2026-11-18"]
    assert set(entry["items"]) == {"3"} and entry["summary"]["en"] == "Two items."
    assert "A: Kolmas." in api.sent[4]["messages"][1]["content"]
