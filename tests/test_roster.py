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
    assert role_of("I viceordförande") == "vice_chair"
    assert role_of("Ordförande") == "chair"
    assert role_of("Ersättare") == "deputy"
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
                ("Limnéll Jarno", "valtuutettu", True),
                ("Makinen Ville", "valtuutettu", True),
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
            PartyRow("Limnell Jarno", "KOK", "elected", "t", 5000),  # é and e are one letter
            PartyRow("Mäkinen Ville", "PS", "elected", "t", 5),  # a and ä are not
        ]
    )
    assert matched == 3
    assert missing == ["Korhonen Anna", "Makinen Ville"]
    out = r.to_json()
    PeopleFile.model_validate(out)
    by_id = {p["id"]: p for p in out["persons"]}
    assert set(by_id) == {
        "espoo/virtanen-matti",
        "espoo/makinen-juha-j",
        "espoo/korhonen-anna",
        "espoo/limnell-jarno",
        "espoo/makinen-ville",
    }
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


def test_name_order_from_the_candidate_list():
    r = Roster("vantaa", "vantaa/kaupunginvaltuusto")
    # Vantaa council covers list deputies first-name first
    r.add_meeting(_meeting("vantaa/kaupunginvaltuusto", "2025-09-15", [("Jari Sainio", "varajäsen", True)]))
    r.add_meeting(_meeting("vantaa/kaupunginvaltuusto", "2025-09-16", [("Mikko Outo", "varajäsen", True)]))
    r.add_parties([PartyRow("Sainio Jari", "SDP", "deputy", "t", 300)])
    names = {p["id"]: p["name"] for p in r.to_json()["persons"]}
    assert names["vantaa/sainio-jari"] == "Jari Sainio"
    assert "vantaa/mikko-outo" in names  # without a candidate row the printed order stays


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


def test_accent_variants_are_one_person():
    r = Roster("espoo", "espoo/valtuusto")
    for date, name in (
        ("2025-06-16", "Limnéll Jarno"),
        ("2025-08-25", "Limnell Jarno"),
        ("2025-09-22", "Limnell Jarno"),
    ):
        r.add_meeting(_meeting("espoo/valtuusto", date, [(name, "puheenjohtaja", True)]))
    (p,) = r.to_json()["persons"]
    assert (p["id"], p["name"], p["aliases"]) == (
        "espoo/limnell-jarno",
        "Jarno Limnell",
        ["Limnell Jarno", "Limnéll Jarno"],
    )


def test_nameless_attendance_entry_gets_no_person():
    r = Roster("espoo", "espoo/valtuusto")
    r.add_meeting(
        _meeting(
            "espoo/valtuusto",
            "2025-06-16",
            [("Virtanen Matti", "valtuutettu", True), ("–", "valtuutettu", True)],
        )
    )
    out = r.to_json()
    assert all(p["id"].split("/")[1] for p in out["persons"])
    assert all(m["person_id"].split("/")[1] for m in out["memberships"])


def test_registry_name_forms():
    """Forms seen on registry municipalities' minutes (M15): a party after the name, an initial
    glued to the first name and printed first-name first, and notes in the name column."""
    r = Roster("x", "x/valtuusto")
    r.add_meeting(
        _meeting(
            "x/valtuusto",
            "2025-09-01",
            [
                ("Aaltonen Minna, KOK", "valtuutettu", True),
                ("Ari.M Laitinen", "valtuutettu", True),
                ("Kokouksessa tauko klo 17:06-17:35", "valtuutettu", True),
                ("- -", "valtuutettu", True),
                ("Henri Ihander (varajäsen", "varajäsen", True),
            ],
        )
    )
    r.add_meeting(_meeting("x/valtuusto", "2025-10-01", [("Aaltonen Minna", "valtuutettu", True)]))
    matched, missing = r.add_parties(
        [
            PartyRow("Aaltonen Minna", "KOK", "elected", "t", 100, surname="Aaltonen", first="Minna"),
            PartyRow("Laitinen Ari", "SDP", "elected", "t", 200, surname="Laitinen", first="Ari"),
            PartyRow("Ihander Henri", "PS", "deputy", "t", 20, surname="Ihander", first="Henri"),
        ]
    )
    assert (matched, missing) == (3, [])
    by_id = {p["id"]: p for p in r.to_json()["persons"]}
    assert set(by_id) == {"x/aaltonen-minna", "x/laitinen-ari-m", "x/ihander-henri"}
    assert by_id["x/ihander-henri"]["aliases"] == ["Henri Ihander (varajäsen"]
    assert by_id["x/aaltonen-minna"]["aliases"] == ["Aaltonen Minna", "Aaltonen Minna, KOK"]
    assert by_id["x/laitinen-ari-m"]["name"] == "Ari.M Laitinen"
    assert by_id["x/laitinen-ari-m"]["party"] == "SDP"


def test_printed_forms_of_one_person_share_a_candidacy():
    r = Roster("x", "x/valtuusto")
    r.add_meeting(
        _meeting(
            "x/valtuusto",
            "2025-09-01",
            [("Laitinen Pekka", "valtuutettu", True), ("Laitinen Pekka J.", "varavaltuutettu", True)],
        )
    )
    matched, _ = r.add_parties([PartyRow("Laitinen Pekka", "KESK", "elected", "t", 1, surname="Laitinen")])
    assert matched == 2
    parties = {p["id"]: p.get("party") for p in r.to_json()["persons"]}
    assert parties == {"x/laitinen-pekka": "KESK", "x/laitinen-pekka-j": "KESK"}


def test_override_joins_a_printed_name_to_its_candidate():
    r = Roster("x", "x/valtuusto")
    r.add_meeting(_meeting("x/valtuusto", "2025-09-01", [("Kauste Mika", "valtuutettu", True)]))
    rows = [PartyRow("Kauste Mikki", "PS", "elected", "t", 700, surname="Kauste", first="Mikki")]
    assert r.add_parties(rows) == (0, ["Kauste Mika"])
    assert r.add_parties(rows, {"Kauste Mika": "Kauste Mikki"}) == (1, [])
    (p,) = r.to_json()["persons"]
    assert (p["party"], p["aliases"]) == ("PS", ["Kauste Mika"])
