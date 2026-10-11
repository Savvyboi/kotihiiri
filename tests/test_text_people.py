from kunta.bodies import default_included, guess_kind
from kunta.models import SectionType
from kunta.pdf import drop_repeated_lines, join_lines
from kunta.people import Candidate, name_key, normalize_name, resolve
from kunta.text import classify_heading, contains_pii, strip_pii


def test_strip_pii():
    s = (
        "Lisätietoja: matti.virtanen@hel.fi, puhelin 09 310 12345 tai +358 40 123 4567. "
        "Päätös tehtiin 23.9.2026 äänin 36–34, § 261, HEL 2026-008342."
    )
    out = strip_pii(s)
    assert "@" not in out and "310 12345" not in out and "123 4567" not in out
    assert "23.9.2026" in out and "36–34" in out and "HEL 2026-008342" in out
    assert not contains_pii(out)
    assert contains_pii(s)


def test_classify_heading():
    assert classify_heading("Päätösehdotus") == SectionType.proposal
    assert classify_heading("Päätös") == SectionType.decision
    assert classify_heading("Päätöshistoria") == SectionType.history
    assert classify_heading("Esittelijän perustelut") == SectionType.background
    assert classify_heading("Muutoksenhaku") is None
    assert classify_heading("Jotain muuta") == SectionType.other


def test_body_rules():
    assert default_included("Kaupunkiympäristölautakunta")
    assert default_included("Tarkastuslautakunta")
    for name in [
        "Sosiaali-, terveys- ja pelastuslautakunnan yksilöasioiden jaosto",
        "Keskusvaalilautakunta",
        "Nuorisoneuvosto",
        "Testitoimielin",
        "Rakennuslupajaosto",
        "Stadsfullmäktige",
        "Tikkurilan aluetoimikunta",
    ]:
        assert not default_included(name), name
    assert guess_kind("Kaupunginvaltuusto") == "council"
    assert guess_kind("Kaupunginhallituksen konsernijaosto") == "section"


def test_name_normalization():
    assert normalize_name("Valtuutettu Siri Ahokas (vastauspuheenvuoro)") == "Siri Ahokas"
    assert name_key("Virtanen, Matti") == name_key("Matti Virtanen") == name_key("Virtanen Matti")


def test_resolve_exact_fuzzy_and_ambiguous():
    cands = [
        Candidate("espoo/virtanen-matti", ("Matti Virtanen",)),
        Candidate("espoo/makinen-juha", ("Juha J. Mäkinen",)),
    ]
    assert resolve("Virtanen Matti", cands).person_id == "espoo/virtanen-matti"
    typo = resolve("Valtuutettu Matti Virttanen", cands)
    assert typo.person_id == "espoo/virtanen-matti" and typo.confidence < 1
    assert resolve("Liisa Korhonen", cands).person_id is None
    twins = [Candidate("x/a", ("Anna Laine",)), Candidate("x/b", ("Anna Laine",))]
    assert resolve("Anna Laine", twins).person_id is None


def test_pdf_helpers():
    pages = [["Helsingin kaupunki", f"{i} / 3", "text " + str(i)] for i in range(1, 4)]
    assert drop_repeated_lines(pages) == [["text 1"], ["text 2"], ["text 3"]]
    assert (
        join_lines(["kaupun-", "ginvaltuusto", "Uusi-", "Kaupunki"]) == "kaupunginvaltuusto\nUusi-\nKaupunki"
    )
