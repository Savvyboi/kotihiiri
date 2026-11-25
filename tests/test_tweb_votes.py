"""Votes, motions and column covers in the Tweb towns sampled on 2026-11-26 (Lieto, Nokia, Akaa,
Varkaus, Hamina, Kerava, Muurame; Kangasala and Varkaus covers)."""

from pathlib import Path

import pytest

from kunta.models import MotionKind, Outcome
from kunta.parsers import tweb as tp

FIXTURES = Path(__file__).parent / "fixtures" / "tweb_votes"


def case(name: str):
    lines = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    doc = tp.parse_item_lines(lines, lines[0])
    _, _, deliberation = tp.item_sections(doc)
    motions, prose = tp.parse_case(deliberation)
    return doc, motions, prose


@pytest.mark.parametrize(
    "name, motion, votes",
    [
        # Lieto: "106/16.11.2026" blocks; the board's named 7–4 vote stays in its history block
        (
            "lieto",
            ("Lotta Salminen", ["Johanna Hätinen"], MotionKind.send_back, Outcome.rejected),
            [(26, 13)],
        ),
        # Nokia: "Kannatus: …", "A = JAA, B = EI", "… hyväksyttiin äänin 30 - 13"
        (
            "nokia",
            ("Niina Melkko", ["Timo Lehtonen", "Eleanora Mäkinen"], None, Outcome.rejected),
            [(30, 13)],
        ),
        (
            "nokia85",
            ("Maija Alfreds", ["Niina Melkko", "Jonna Junnila"], MotionKind.send_back, Outcome.adopted),
            [(20, 23)],
        ),
        # Akaa: "KV 09.11.2026" / "§ 69", seconders in a sentence of their own, the motion won
        (
            "akaa",
            ("Majka Nurminen", ["Laura Väisänen", "Heli Piirainen", "Mika Lohi"], None, Outcome.adopted),
            [(16, 19)],
        ),
        # Hamina: number words with digits, voters in brackets, one blank vote
        ("hamina", ("Antti Pakkanen", ["Jani Jaakkola", "Tero Pasi"], None, Outcome.rejected), [(5, 3)]),
        # Kerava: "sai 15 JAA-ääntä ja … 36 EI-ääntä", the send-back won
        (
            "kerava",
            (
                "Timo Laaninen",
                ["Tuomo Suihkonen", "Inna Kallioinen", "Pia Lohikoski", "Karoliina Kaarivirta"],
                MotionKind.send_back,
                Outcome.adopted,
            ),
            [(15, 36)],
        ),
        # Muurame: "Pohjaesitys voitti äänin 25-2"
        (
            "muurame",
            ("Viivi Marjamäki", ["Tuomo Leinonen"], MotionKind.send_back, Outcome.rejected),
            [(25, 2)],
        ),
    ],
)
def test_votes_and_motions(name, motion, votes):
    _, motions, prose = case(name)
    [mo] = motions
    prop, secs, kind, outcome = motion
    assert mo.proposer_ref.raw == prop
    assert [s.raw for s in mo.seconder_refs] == secs
    if kind is not None:
        assert mo.kind == kind
    assert mo.outcome == outcome
    assert [(p.a, p.b) for p in prose] == votes


def test_hamina_names_and_blank():
    _, _, [pv] = case("hamina")
    assert pv.tyhja == 1
    assert len(pv.names[tp.Choice.jaa]) == 5 and len(pv.names[tp.Choice.ei]) == 3


def test_varkaus_verb_first_and_unseconded():
    doc, motions, [pv] = case("varkaus")
    assert not doc.blocks  # one handling, no header: the item text is the case
    assert [(m.proposer_ref.raw, [s.raw for s in m.seconder_refs], m.outcome) for m in motions] == [
        ("Tiina Grönlund", [], Outcome.rejected),
        ("Tiina Grönlund", ["Pekka Kaatrasalo"], Outcome.rejected),
    ]
    assert (pv.a, pv.b, pv.jaa_label) == (25, 10, "kaupunginhallituksen pohjaesitys")


def words(name: str) -> list[tuple[float, float, float, str]]:
    out = []
    for line in (FIXTURES / f"{name}_words.txt").read_text(encoding="utf-8").splitlines():
        top = 0.0
        for cell in line.split("|"):
            t = cell.split()
            if len(t) == 4:
                top = float(t.pop(0))
            out.append((top, float(t[0]), float(t[1]), t[2]))
    return out


def test_kangasala_two_columns():
    got = {
        p.name: (p.role, p.present, p.note) for p in tp.parse_cover_columns(words("kangasala")).participants
    }
    assert got["Aalto Olli"] == ("jäsen", True, "saapui §:n 75 aikana klo 15.10")
    assert got["Kuusjärvi Topi-Pekka"] == ("jäsen", True, None)
    assert got["Haavisto Jussi"][2] == "saapui §:n 74 jälkeen klo 15.04"
    assert got["Aalto Petra"] == ("jäsen", False, None)
    assert got["Tanhuanpää Salla"] == ("varajäsen", True, None)
    assert got["Sillman-Sola Jonna"] == ("hallintojohtaja, pöytäkirjanpitäjä", True, None)


def test_varkaus_three_columns():
    cover = tp.parse_cover_columns(words("varkaus"))
    got = {p.name: (p.role, p.present, p.note) for p in cover.participants}
    assert got["Suhonen Timo"] == ("puheenjohtaja", True, None)  # listed again in the grid: kept once
    assert [p.name for p in cover.participants].count("Suhonen Timo") == 1
    assert got["Kosunen Antti"] == ("jäsen", True, "poissa klo 18.01–18.03 § 68")
    assert got["Pulliainen Paula"] == ("jäsen", True, None)
    assert got["Kaatrasalo Pekka"] == ("jäsen", False, None)
    assert got["Kärkkäinen Saija"] == ("varajäsen", True, None)


def test_doc_noise_dropped():
    assert tp.readable_lines(["Käsittely", "34GHIJKLyz¨©ª«®¸»½âí\x01\x02", "Päätös"]) == [
        "Käsittely",
        "Päätös",
    ]
