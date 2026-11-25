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


def test_kangasala_whole_grid_over_two_pages():
    ps = tp.parse_cover_columns(words("kangasala")).participants
    members = [p for p in ps if p.role == "jäsen" and p.present]
    assert len(members) == 50
    assert members[-1].name == "Kouhia Raimo"
    got = {p.name: (p.role, p.note) for p in ps}
    assert got["Jussila Heidi"] == ("jäsen", "saapui §:n 75 aikana klo 15.10")
    assert got["Holma Elina"] == ("hallinnon sihteeri", None)
    assert got["Toivonen Sonja"] == ("nuorisovaltuuston edustaja", None)
    assert "Asiat" not in str(got)


# -- round 5: the #56 dry run's misreads ------------------------------------------------------


def prose_case(name: str):
    return tp.parse_case((FIXTURES / f"{name}.txt").read_text(encoding="utf-8").splitlines())


def summary(motions):
    return [(m.proposer_ref.raw, [s.raw for s in m.seconder_refs], m.outcome) for m in motions]


def test_akaa_same_counts_are_separate_votes_with_their_own_labels():
    motions, prose = prose_case("akaa_kv75")
    assert [(p.a, p.b, p.ei_label) for p in prose] == [
        (21, 14, "Jaakko Leinosen ehdotus"),
        (24, 11, "Anton Murolan ehdotus"),
        (9, 26, "Jouni Vaittisen ehdotus"),
        (4, 31, "Jouni Vaittisen ehdotus"),
        (28, 7, "Saija Roinisen ehdotus"),
        (28, 7, "Majka Nurmisen ehdotus"),  # "Maj-/ka", and no "Akaan kaupunki" page header
    ]
    assert prose[4].jaa_label == "kaupunginhallituksen ehdotus"
    got = dict((n, o) for n, _, o in summary(motions))
    # the first vote is Väisänen (Jaa) against Vaittinen (Ei); Vaittinen then beats the base
    assert got["Laura Väisänen"] == Outcome.rejected
    assert got["Jouni Vaittinen"] == Outcome.adopted


def test_hameenlinna_several_seconders_in_the_genitive():
    motions, prose = prose_case("hml49")
    assert [(p.a, p.b, p.tyhja) for p in prose] == [(28, 18, 5), (28, 18, 5), (28, 23, 0)]
    assert summary(motions) == [
        ("Anne Laatikainen", ["Timo Viitanen", "Tiia Nurminen", "Kylli Kylliäinen"], Outcome.rejected),
        ("Anne Laatikainen", ["Timo Viitanen", "Tiia Nurminen", "Kylli Kylliäinen"], Outcome.rejected),
        ("Timo Viitanen", ["Tiia Nurminen"], Outcome.rejected),
    ]


def test_raasepori_both_sides_name_a_motion():
    motions, prose = prose_case("raasepori_142")
    assert [(p.jaa_label, p.ei_label) for p in prose] == [
        ("Vilanders förslag", "Barmans förslag"),
        ("Stadsstyrelsens förslag", "Barmans förslag"),
    ]
    assert summary(motions) == [
        ("Dennis Barman", ["Linnéa Henriksson"], Outcome.adopted),
        ("Isak Vilander", ["Alexandra Lundmark"], Outcome.rejected),
    ]


def test_muurame_option_result():
    motions, [pv] = prose_case("muurame98")
    assert (pv.a, pv.b, pv.jaa_label, pv.ei_label) == (23, 3, "Pohjaesitys", "vastaesitys")
    assert summary(motions) == [("Viivi Marjamäki", ["Tuomo Leinonen"], Outcome.rejected)]


def test_nokia_named_lists_and_unpunctuated_seconder():
    motions, [pv] = prose_case("nokia69")
    assert (pv.a, pv.b) == (6, 3)
    assert pv.names[tp.Choice.ei] == ["Teresa Kvick", "Anneli Lehtonen", "Kaisa Räsänen"]
    assert len(pv.names[tp.Choice.jaa]) == 6
    assert summary(motions) == [("Kaisa Räsänen", ["Anneli Lehtonen"], Outcome.rejected)]


def test_rauma_roll_call_by_names_and_comma_before_seconder():
    motions, [pv] = prose_case("rauma_kh37")
    assert (pv.a, pv.b) == (5, 4)
    assert pv.names[tp.Choice.ei] == ["Sari Seimelä", "Kalle Leppikorpi", "Heidi Hiljanen", "Jari Laihonen"]
    assert pv.ei_label == "Sari Seimelän ehdotus"
    assert summary(motions) == [("Sari Seimelä", ["Heidi Hiljanen"], Outcome.rejected)]


def test_pirkkala_heading_line_and_stem_change():
    motions, [pv] = prose_case("pirkkala3")
    assert (pv.a, pv.b) == (32, 11)
    assert summary(motions) == [("Heikki Riihimäki", ["Veli-Matti Ahtiainen"], Outcome.rejected)]


def test_valkeakoski_unanimous_adoption():
    motions, prose = prose_case("valkeakoski_kh14")
    assert prose == []
    assert summary(motions) == [("Takku", ["Selkee"], Outcome.adopted)]


PDF = Path(__file__).parent / "fixtures" / "tweb_pdf"


def pdf_doc(name: str):
    return tp.parse_item_lines((PDF / f"{name}.txt").read_text(encoding="utf-8").splitlines())


def test_valkeakoski_handling_after_tiedoksi_is_the_meetings_own():
    doc = pdf_doc("valkeakoski_kh_2025-04-14_80")
    assert [b.header for b in doc.blocks] == ["KH 20.6.2022 § 192", "KV 27.6.2022 § 67", "KH 14.4.2025 § 80"]
    sections, _, deliberation = tp.item_sections(doc)
    assert deliberation == []  # the 2022 council votes stay in their history block
    assert [(s.type, s.heading) for s in sections][-2:] == [
        (tp.SectionType.proposal, "Ehdotus"),
        (tp.SectionType.decision, "Päätös"),
    ]
    [pv] = tp.parse_prose(doc.blocks[1].lines)
    assert pv.jaa_label == "KH:n ehdotus"


def test_varkaus_list_of_handlings_at_the_top():
    import datetime as dt

    doc = pdf_doc("varkaus_kv_2026-09-28_68")
    tp.end_at_meeting(doc, dt.date(2026, 9, 28), 68)
    assert [b.header for b in doc.blocks][-1] == "Kaupunginvaltuusto 28.9.2026 § 68"
    _, _, deliberation = tp.item_sections(doc)
    motions, [pv] = tp.parse_case(deliberation)
    assert (pv.a, pv.b) == (31, 4)
    assert summary(motions) == [("Hilkka Koponen", ["Kirsti Lumiala"], Outcome.rejected)]


def test_hamina_html_with_a_bogus_heading_and_no_header_for_the_council():
    html = (Path(__file__).parent / "fixtures" / "tweb_html" / "hamina_kv_2026-04-20_15.html").read_text(
        encoding="utf-8"
    )
    doc = tp.parse_item_html(html)
    assert doc.case_number == "Hamina/172/2026"
    assert [b.header for b in doc.blocks] == [
        "Kasvatus ja koulutus -valiokunta 7.4.2026 § 18",
        "Kaupunginhallitus 13.4.2026 § 68",
        "Kaupunginvaltuusto 20.4.2026 § 15",
    ]
    sections, _, deliberation = tp.item_sections(doc)
    assert [s.type for s in sections][-3:] == [
        tp.SectionType.proposal,
        tp.SectionType.deliberation,
        tp.SectionType.decision,
    ]
    motions, [pv] = tp.parse_case(deliberation)
    assert (pv.a, pv.b, pv.ei_label) == (31, 6, "Pakkasen vastaehdotus")  # not the board's 7–2
    assert summary(motions) == [
        (
            "Antti Pakkanen",
            ["Peter Muurman", "Anu Oikkonen", "Janne Nyholm", "Jani Jaakkola"],
            Outcome.rejected,
        )
    ]
