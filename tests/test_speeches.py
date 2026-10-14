from kunta import jsonio
from kunta.parsers.speeches_helsinki import parse_heading, parse_transcript
from kunta.speeches import Resolver

# The layout of a Helsinki "keskustelupöytäkirja" after page headers are dropped (fictional names).
LINES = """14 — 2026
Kokousaika: 23.9.2026 klo 18.00 – 21.43
Keskustelupöytäkirjaan on kirjattu vain ne kaupunginvaltuuston esityslistan asiakohdat,
joissa on käytetty puheenvuoro.
Sisällysluettelo
256 § ............................................................ 6
Esityslistan asia nro 8 ............................................. 6
Testikaupungin ympäristöraportti 2025 ............................... 6
Apulaispormestari Aino Esimerkki .................................... 6
Valtuutettu Bertta Testinen (vastauspuheenvuoro) .................... 7
Ledamoten Carl Provsson (replik) .................................... 7
262§ ................................................................ 9
Esityslistan asia nro 14 ............................................ 9
Valtuutettu Bertta Testisen aloite kaupungin tukemasta
joukkoliikennelipusta ............................................... 9
Valtuutettu Bertta Testinen ......................................... 9
256 §
Esityslistan asia nro 8
Testikaupungin ympäristöraportti
2025
Apulaispormestari Aino Esimerkki
Kiitos, hyvä puheenjohtaja. Arvon valtuutetut.
On ilo esitellä lyhyesti ympäristöraportti vuodelta 2025, joka kertoo ympäristön-
suojelun tavoitteiden etenemisestä.
Kiitos.
Valtuutettu Bertta Testinen (vastauspuheenvuoro)
Valtuutettu Esimerkin puheenvuoron aikana kuulimme hyviä uutisia. Soittakaa
minulle numeroon 040 123 4567.
Ledamoten Carl Provsson (replik)
Tack, ordförande.
262§
Esityslistan asia nro 14
Valtuutettu Bertta Testisen aloite kaupungin tukemasta joukkoliikennelipusta
Valtuutettu Bertta Testinen
Arvoisa puheenjohtaja.""".splitlines()

MID = "helsinki/kaupunginvaltuusto/2026-09-23"
ITEMS = {8: (f"{MID}/8", 256), 14: (f"{MID}/14", 999)}


def test_parse_heading():
    h = parse_heading("Valtuutettu Bertta Testinen (vastauspuheenvuoro)")
    assert (h.title, h.name, h.kind, h.lang) == ("Valtuutettu", "Bertta Testinen", "reply", "fi")
    h = parse_heading("Nuorisoneuvoston edustaja Rosa Esimerkki Saarinen")
    assert (h.title, h.name) == ("Nuorisoneuvoston edustaja", "Rosa Esimerkki Saarinen")
    assert parse_heading("Ledamoten Carl Provsson (replik)").lang == "sv"
    assert parse_heading("Esityslistan asia nro 8") is None


def test_parse_transcript():
    speeches, expected = parse_transcript(LINES, MID, ITEMS, "u")
    assert expected == 4
    assert [(s.speaker_title, s.speaker_ref.raw, s.kind) for s in speeches] == [
        ("Apulaispormestari", "Aino Esimerkki", "speech"),
        ("Valtuutettu", "Bertta Testinen", "reply"),
        ("Ledamoten", "Carl Provsson", "reply"),
        ("Valtuutettu", "Bertta Testinen", "speech"),
    ]
    first, reply, swedish, last = speeches
    assert first.id == "helsinki/kaupunginvaltuusto/2026-09-23/s1" and first.ordinal == 1
    assert first.item_id == "helsinki/kaupunginvaltuusto/2026-09-23/8"
    assert first.text == (
        "Kiitos, hyvä puheenjohtaja. Arvon valtuutetut.\n\n"
        "On ilo esitellä lyhyesti ympäristöraportti vuodelta 2025, joka kertoo ympäristönsuojelun "
        "tavoitteiden etenemisestä.\n\nKiitos."
    )
    # A sentence starting "Valtuutettu" inside a speech is text, not a new speaker.
    assert reply.text.startswith("Valtuutettu Esimerkin puheenvuoron aikana")
    assert "040" not in reply.text and "[poistettu]" in reply.text
    assert swedish.lang == "sv"
    # The pykälä printed in the transcript differs from the item's: the speech is not linked.
    assert last.item_id is None and last.text == "Arvoisa puheenjohtaja."


def test_resolver(tmp_path):
    def person(first, last):
        pid = f"helsinki/{last.lower()}-{first.lower()}"
        return {"id": pid, "name": f"{first} {last}", "sort_name": f"{last} {first}", "aliases": []}

    people = {
        "persons": [
            person("Bertta", "Testinen"),
            person("Aino", "Esimerkki"),
            person("Aino", "Virtanen"),
            person("Pekka", "Virtanen"),
        ]
    }
    jsonio.write(tmp_path / "people.json", people)
    r = Resolver(jsonio.read(tmp_path / "people.json"))
    assert r.resolve("Bertta Testinen") == ("helsinki/testinen-bertta", 1.0)
    assert r.resolve("Testinen")[0] == "helsinki/testinen-bertta"  # surname alone, unique
    assert r.resolve("Virtanen") == (None, None)  # two Virtanens
    assert r.resolve("Aino Esimerkkki")[0] == "helsinki/esimerkki-aino"  # one doubled letter
    assert r.resolve("Matti Muukalainen") == (None, None)
