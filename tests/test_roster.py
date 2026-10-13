import json

from kunta import jsonio
from kunta.models import PeopleFile
from kunta.people_sources import statfin
from kunta.roster import PartyRow, Roster, build, role_of, split_name


def test_role_of():
    assert role_of("valtuutettu") == "member"
    assert role_of("jäsen") == "member"
    assert role_of("Medlem") == "member"
    assert role_of("Varajäsen") == "deputy"
    assert role_of("puheenjohtaja § 73-76") == "chair"
    assert role_of("Valtuuston pj.") == "chair"
    assert role_of("2. Varapuheenjohtaja") == "vice_chair"
    assert role_of("valtuuston 1. vpj.") == "vice_chair"
    assert role_of("kaupunginhallituksen I varapuheenjohtaja") is None  # a guest at the council
    for official in (
        "kaupunginjohtaja",
        "nuorisovaltuuston edustaja",
        "juristi, sihteeri",
        "valtuustoryhmän pj.",
    ):
        assert role_of(official) is None, official


def test_split_name():
    assert split_name("Virtanen Matti") == ("Virtanen", "Matti")
    assert split_name("af Testsson Anna Maria") == ("af Testsson", "Anna Maria")
    assert split_name("Blomqvist-Kakko Minea") == ("Blomqvist-Kakko", "Minea")


def _meeting(body, date, attendance, stage="minutes"):
    return {
        "meeting": {
            "body_id": body,
            "date": date,
            "stage": stage,
            "attendance": [
                {"person_ref": {"raw": n}, "role_text": r, "present": p} for n, r, p in attendance
            ],
        },
        "items": [],
    }


def test_roster_from_attendance_and_parties():
    r = Roster("espoo", "espoo/valtuusto")
    r.add_meeting(
        _meeting(
            "espoo/valtuusto",
            "2025-06-16",
            [
                ("Virtanen Matti", "puheenjohtaja", True),
                ("Mäkinen Juha J.", "valtuutettu", True),
                ("Korhonen Anna", "valtuutettu", True),
                ("Lahti Pekka", "kaupunginjohtaja", True),
            ],
        )
    )
    r.add_meeting(_meeting("espoo/valtuusto", "2025-09-01", [("Virtanen Matti", "valtuutettu", True)]))
    r.add_meeting(_meeting("espoo/kaupunginhallitus", "2025-09-08", [("Korhonen Anna", "jäsen", True)]))
    r.add_meeting(
        _meeting("espoo/valtuusto", "2025-09-15", [("Nobody Here", "valtuutettu", True)], stage="agenda")
    )
    matched, missing = r.add_parties(
        [
            PartyRow("Virtanen Matti", "KOK", "elected", "t", 900),
            PartyRow("Mäkinen Juha", "SDP", "deputy", "t", 120),
            PartyRow("Korhonen Anna", "VIHR", "elected", "t", 50),
            PartyRow("Korhonen Anna", "PS", "not_elected", "t", 3),  # a shared name is never guessed
            PartyRow("Uusi Henkilö", "KESK", "elected", "t", 10),  # never creates a person
        ]
    )
    assert matched == 2
    assert missing == ["Korhonen Anna"]
    out = r.to_json()
    PeopleFile.model_validate(out)
    by_id = {p["id"]: p for p in out["persons"]}
    assert set(by_id) == {"espoo/virtanen-matti", "espoo/makinen-juha-j", "espoo/korhonen-anna"}
    assert by_id["espoo/virtanen-matti"]["party"] == "KOK"
    assert by_id["espoo/virtanen-matti"]["name"] == "Matti Virtanen"
    assert by_id["espoo/makinen-juha-j"]["election"] == {
        "year": 2025,
        "party": "SDP",
        "result": "deputy",
        "votes": 120,
        "source": "t",
    }
    assert "party" not in by_id["espoo/korhonen-anna"]
    ms = [(m["person_id"], m["body_id"], m["role"], m["start"], m["end"]) for m in out["memberships"]]
    assert ("espoo/virtanen-matti", "espoo/valtuusto", "chair", "2025-06-16", "2025-06-16") in ms
    assert ("espoo/virtanen-matti", "espoo/valtuusto", "member", "2025-09-01", "2025-09-01") in ms
    assert ("espoo/korhonen-anna", "espoo/kaupunginhallitus", "member", "2025-09-08", "2025-09-08") in ms


def test_helsinki_vote_tables_give_groups(tmp_path):
    mf = {
        "meeting": {
            "id": "helsinki/kaupunginvaltuusto/2025-09-10",
            "body_id": "helsinki/kaupunginvaltuusto",
            "date": "2025-09-10",
            "stage": "minutes",
            "attendance": [],
        },
        "items": [
            {
                "votes": [
                    {
                        "ballots": [
                            {
                                "person_ref": {"raw": "Virtanen, Matti"},
                                "choice": "jaa",
                                "group_text": "Kokoomuksen valtuustoryhmä",
                            },
                            {"person_ref": {"raw": "Korhonen, Anna"}, "choice": "ei"},
                        ]
                    }
                ]
            }
        ],
    }
    jsonio.write(tmp_path / "helsinki/meetings/2025/kaupunginvaltuusto--2025-09-10.json", mf)
    out = build("helsinki", "helsinki/kaupunginvaltuusto", tmp_path).to_json()
    assert [p["id"] for p in out["persons"]] == ["helsinki/virtanen-matti"]
    assert out["memberships"][0]["group"] == "Kokoomuksen valtuustoryhmä"


def test_roster_output_is_deterministic():
    def make(order):
        r = Roster("tampere", "tampere/kaupunginvaltuusto")
        for n in order:
            r.add_meeting(_meeting("tampere/kaupunginvaltuusto", "2025-06-16", [(n, "jäsen", True)]))
        return jsonio.dumps(r.to_json())

    assert make(["Aalto Aino", "Bäck Bo", "Aalto Aino"]) == make(["Bäck Bo", "Aalto Aino"])


META = {
    "variables": [
        {"code": "timeperiod_y", "values": ["2025"], "valueTexts": ["2025"]},
        {
            "code": "vaaliehdokas_25_20250101",
            "values": ["1", "2", "3"],
            "valueTexts": [
                "Virtanen Matti / KOK / Espoo",
                "Mäkinen Juha / SDP / Espoo",
                "Aalto Aino / VIHR / Vantaa",
            ],
        },
        {"code": "contentscode", "values": ["kvaa-aanet_yht", "kvaa_valinta"], "valueTexts": ["a", "b"]},
    ]
}
CSV = (
    '﻿"Vuosi","Ehdokas","Äänimäärä yhteensä","Valintatieto (1=valittu, 2=varalla, 3=ei valittu)"\n'
    '"2025","Virtanen Matti / KOK / Espoo",900,1\n'
    '"2025","Mäkinen Juha / SDP / Espoo",120,2\n'
)


def test_statfin_parsing():
    assert statfin.parse_candidate("af Testsson Anna / RKP / Espoo") == ("af Testsson Anna", "RKP", "Espoo")
    assert statfin.parse_candidate("Yhteislista") is None
    code, names = statfin.candidate_codes(META, "Espoo")
    assert code == "vaaliehdokas_25_20250101" and set(names) == {"1", "2"}
    rows = statfin.parse_csv(CSV, names)
    assert [(r.name, r.party, r.result, r.votes) for r in rows] == [
        ("Virtanen Matti", "KOK", "elected", 900),
        ("Mäkinen Juha", "SDP", "deputy", 120),
    ]
    people = {
        "persons": [
            {
                "sort_name": "Virtanen Matti",
                "election": {"year": 2025, "party": "KOK", "result": "elected", "votes": 900, "source": "s"},
            }
        ]
    }
    assert statfin.rows_from_people(json.loads(json.dumps(people)))[0].party == "KOK"
