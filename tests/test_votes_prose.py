"""Votes read from the minutes text alone (kunta/parsers/votes_prose.py). The sentences are the
registry municipalities' own wording, as the 2026-10-17 vote audit printed them."""

from kunta.models import Choice
from kunta.parsers.votes_prose import parse

URL = "https://example.invalid/item"


def votes(*lines):
    return parse(list(lines), item_url=URL)


def counts(v):
    return (v.counts.jaa, v.counts.ei, v.counts.tyhja, v.counts.poissa)


def names(v, choice):
    return [b.person_ref.raw for b in v.ballots if b.choice == choice]


def test_counts_with_names_in_brackets_and_restated_result():
    [v] = votes(
        "Puheenjohtajan esityksestä päätettiin suorittaa asiassa äänestys siten, että ne jotka kannattavat "
        "asian käsittelyn jatkamista äänestävät JAA ja ne, jotka kannattavat Maija Kuivalaisen tekemää "
        "kannatettua ehdotusta asian palauttamisesta uudelleen valmisteltavaksi äänestävät EI.",
        "Suoritetussa äänestyksessä annettiin 9 JAA-ääntä (Petja Vuojärvi, Kari Surakka, Paula Puhakka, "
        "Eero Bogdanoff, Saara Koikkalainen, Timo Puustinen, Jukka Mutanen, Tiina Kuokkanen ja Matti Pesonen) "
        "ja 2 EI-ääntä (Maija Kuivalainen ja Anette Huovinen).",
        "Puheenjohtaja totesi äänestyksen tulokseksi tulleen 9–2.",
    )
    assert counts(v) == (9, 2, 0, 0)
    assert len(v.ballots) == 11 and not v.needs_review
    assert names(v, Choice.ei) == ["Maija Kuivalainen", "Anette Huovinen"]
    assert v.jaa_label == "Asian käsittelyn jatkamista"
    assert v.ei_label.startswith("Maija Kuivalaisen tekemää")


def test_quoted_choices_and_a_named_blank():
    [v] = votes(
        "Suoritetussa äänestyksessä annettiin 4 'JAA' -ääntä (Sakari Pääkkö, Björn Cederberg, "
        "Miia Eskelinen-Fingerroos ja Minna Reijonen), 6 'EI' -ääntä (Aleksi Eskelinen, Tiina Kaartinen, "
        "Marja Berg, Jaakko Kosunen, Vesa Linnanmäki ja Pekka Niiranen) ja yksi 'TYHJÄ' (Sallamaarit Markkanen)."
    )
    assert counts(v) == (4, 6, 1, 0)
    assert len(v.ballots) == 11 and not v.needs_review


def test_named_sides_with_sai():
    [v] = votes(
        "Annetussa äänestyksessä kaupunginjohtajan esitys sai 7 JAA-ääntä (Poukkula Pekka, Pekkala Sari, "
        "Lumijärvi Liisa, Orava Anne-Mari, Äijälä Samuli, Salmela Marko, Ylisirniö Kirsi) ja Anu Mattilan "
        "esitys sai 4 EI-ääntä (Ollanketo Tarja, Nikula Matti, Seppä Jari, Mattila Anu).",
        "Puheenjohtaja totesi, että kaupunginhallitus on äänin 7 - 4, hyväksynyt kaupunginjohtajan esityksen asiassa.",
    )
    assert counts(v) == (7, 4, 0, 0)
    assert v.jaa_label == "Kaupunginjohtajan esitys"
    assert v.ei_label == "Anu Mattilan esitys"
    assert len(v.ballots) == 11


def test_sides_without_printed_choice_take_jaa_then_ei():
    [v] = votes(
        "Äänestys Suoritetussa äänestyksessä kaupunginjohtajan pohjaesitys sai 7 ääntä ja Palorannan vastaesitys sai 5 ääntä."
    )
    assert counts(v) == (7, 5, 0, 0)
    assert v.ei_label == "Palorannan vastaesitys"
    [v] = votes(
        "Äänestys Suoritetussa äänestyksessä kaupunginjohtajan päätösesitys sai 5 ääntä ja jäsen Palorannan esitys 7 ääntä."
    )
    assert counts(v) == (5, 7, 0, 0)


def test_salo_lines():
    [v] = votes(
        "Puheenjohtaja ehdotti, että toimitetaan nimenhuutoäänestys.",
        "Suoritetussa äänestyksessä",
        "Esittelijän pohjaehdotus sai kahdeksan JAA ääntä (Paassilta, Nummentalo, Aaltonen, Poikela, Sadeharju, Valkonen, Wallius, Yli-Jama)",
        "Jäsen Mänkärin ehdotus sai viisi EI ääntä (Lehti, Kymäläinen, Mänkäri, Ruokonen, Friberg)",
    )
    assert counts(v) == (8, 5, 0, 0)
    assert len(v.ballots) == 13


def test_voters_listed_after_the_counts():
    [v] = votes(
        "Äänestyksessä annettiin 2 JAA ääntä ja 11 EI ääntä.",
        "JAA äänestivät Saara Huhmarniemi ja Sanni Jäppinen",
        "EI äänestivät Carl-Johan Kajanti, Anna Sahiluoma, Matti Kaurila, Piia Aallonharja, Antti Kilappa, Anna "
        "Aintila, Ulf Kjerin, Ari Harinen, Anneli Granström, Kati Kaihlaranta ja Timo Haapaniemi.",
    )
    assert counts(v) == (2, 11, 0, 0)
    assert len(v.ballots) == 13 and not v.needs_review


def test_mixed_case_and_words():
    [v] = votes("Äänestyksessä annettiin 9 JAA ääntä, 3 Ei ääntä ja 1 tyhjä ääni.")
    assert counts(v) == (9, 3, 1, 0)
    [v] = votes(
        "Äänestysesitys hyväksyttiin ja suoritetussa äänestyksessä annettiin 35 jaa ääntä, 14 ei ääntä ja kaksi tyhjää ääntä."
    )
    assert counts(v) == (35, 14, 2, 0)
    [v] = votes(
        "Suoritetussa nimenhuutoäänestyksessä annettiin yhteensä yksitoista (11) ääntä, kuusi (6) JAA-ääntä ja viisi (5) EI-ääntä."
    )
    assert counts(v) == (6, 5, 0, 0)
    [v] = votes("Suoritetussa nimenhuutoäänestyksessä annettiin 25 EI- ääntä ja 10 JAA- ääntä.")
    assert counts(v) == (10, 25, 0, 0)
    [v] = votes(
        "Suoritetussa äänestyksessä annettiin 32 kpl JAA-ääntä ja 2 kpl EI –ääntä ja 1 kpl TYHJÄ-ääntä."
    )
    assert counts(v) == (32, 2, 1, 0)
    [v] = votes(
        "Äänestyksen tulos on 32 (kpl) JAA ääntä, 3 (kpl) EI ääntä, 0 (kpl) tyhjä ja 0 (kpl) poissa.",
        "Valtuusto päätti äänin 32-3 hyväksyä kunnanhallituksen esityksen.",
    )
    assert counts(v) == (32, 3, 0, 0)


def test_several_votes_with_equal_counts_stay_apart():
    vs = votes(
        "Äänestysesitys hyväksyttiin ja suoritetussa äänestyksessä annettiin 39 jaa ääntä ja 12 ei ääntä.",
        "Äänestysesitys hyväksyttiin ja suoritetussa äänestyksessä annettiin 32 jaa ääntä ja 19 ei ääntä.",
        "Muutettu äänestysesitys hyväksyttiin ja suoritetussa äänestyksessä annettiin 32 jaa ääntä ja 19 ei ääntä.",
        "Äänestysesitys hyväksyttiin ja suoritetussa äänestyksessä annettiin 46 jaa ääntä ja 5 ei ääntä.",
    )
    assert [counts(v)[:2] for v in vs] == [(39, 12), (32, 19), (32, 19), (46, 5)]


def test_puolesta_and_kannatti():
    [v] = votes(
        "Äänestyksessä palautuksen puolesta äänesti 10 jäsentä, palautusta vastaan äänesti 2 jäsentä ja 1 jäsen äänesti tyhjää.",
        "Puheenjohtaja totesi kasvun ja oppimisen lautakunnan kymmenellä äänellä kahta ääntä vastaan, yhden äänestäessä tyhjää, päättäneen palauttaa asian uudelleenvalmisteluun.",
    )
    assert counts(v) == (10, 2, 1, 0)
    [v] = votes(
        "Äänestyksessä Lievosen lisäysehdotuksen puolesta äänesti 3 jäsentä, sitä vastaan 9 jäsentä ja 1 äänesti tyhjää."
    )
    assert counts(v) == (3, 9, 1, 0)
    [v] = votes(
        "Äänestyksessä kaupunginhallituksen ehdotusta kannatti 32 valtuutettua ja Oskari Rantalan ehdotusta kannatti 33 valtuutettua ja tyhjää äänesti 2 valtuutettua."
    )
    assert counts(v) == (32, 33, 2, 0)
    assert v.ei_label == "Oskari Rantalan ehdotusta"
    [v] = votes(
        "Äänestyksessä asian käsittelyn jatkamista kannatti 33 valtuutettua ja asian palauttamista uudelleen valmisteltavaksi kannatti 33 valtuutettua ja poissa oli 1 valtuutettu."
    )
    assert counts(v) == (33, 33, 0, 1)


def test_savonlinna_two_votes():
    vs = votes(
        "Ensimmäiseksi suoritetussa äänestyksessä esittelijän ehdotuksen puolesta annettiin 3 jaa-ääntä (Valkonen Esa, Suomalainen Tuukka, Tiainen Jarmo) ja Sanna Metsälän ehdotuksen puolesta 8 ei-ääntä (Kilpeläinen Pekka, Metsälä Sanna, Stenberg Eija, Kokko Lea, Backman Anja, Peitsaro Panu, Asikainen Rauni, Laamanen Kirsti).",
        "Toisessa äänestyksessä esittelijän ehdotuksen puolesta annettiin 7 jaa-ääntä (Kilpeläinen Pekka, Kokko Lea, Backman Anja, Peitsaro Panu, Metsälä Sanna, Stenberg Eija, Asikainen Rauni) ja Kirsti Laamasen ehdotuksen puolesta 3 ei-ääntä (Tiainen Jarmo, Valkonen Esa, Suomalainen Tuukka).",
    )
    assert [counts(v)[:2] for v in vs] == [(3, 8), (7, 3)]
    assert all(len(v.ballots) == sum(counts(v)[:2]) for v in vs)


def test_bare_result_is_kept_for_review():
    [v] = votes(
        "Kaupunginvaltuusto päätti äänestyksen jälkeen äänin 35–15 (1 poissa) hylätä Markku Välimäen esittämän toimenpidealoitteen."
    )
    assert counts(v)[:2] == (35, 15) and v.needs_review
    [v] = votes(
        "Esitys hävisi äänestyksessä kaupunginjohtajan pohjaesitykselle äänin 11 (Nylander, Holmström, Ahonen, Söderberg, Lund, Sigfrids, Valasti, Riikonen, Perokorpi, Ryynänen, Hjelt) 2 (Jokisaari, Lybeck)."
    )
    assert counts(v)[:2] == (11, 2) and len(v.ballots) == 13


def test_not_votes():
    assert (
        votes(
            "Suoritetussa lippuäänestyksessä Juho Lukkari sai seitsemän (7) ääntä ja Unto Väisänen kaksi (2) ääntä."
        )
        == []
    )
    assert votes("Äänestyksessä annettiin yhteensä 15 ääntä.") == []
    assert votes("Kuntalain 41 §:n mukaisesti äänestys suoritetaan tarvittaessa kaksivaiheisena.") == []


def test_swedish():
    [v] = votes(
        "Beslut fattades efter omröstning där motförslaget fick 6 röster (Sandelin, Heikkilä, Helander, Kilpelä, Pajoslahti, Partanen) och beredningen 2 röster (Bertell, Pakarinen)."
    )
    assert counts(v)[:2] == (6, 2) and len(v.ballots) == 8


def test_duplicate_sentence_in_two_sections_is_one_vote():
    s = "Suoritetussa äänestyksessä annettiin 9 jaa-ääntä, 4 ei-ääntä."
    assert len(votes(s, s)) == 1


def test_one_side_written_out_and_the_result():
    [v] = votes(
        "Äänestyksessä Hietanen-Tanskasen muutosehdotuksen puolesta äänesti 2 jäsentä ja 9 jäsentä äänesti sitä vastaan.",
        "Puheenjohtaja totesi kasvun ja oppimisen lautakunnan yhdeksällä äänellä kahta ääntä vastaan hylänneen Hietanen-Tanskasen muutosehdotuksen.",
    )
    assert counts(v)[:2] == (2, 9) and not v.needs_review
    assert v.jaa_label == "Hietanen-Tanskasen muutosehdotuksen puolesta"


def test_names_then_total():
    [v] = votes(
        "Puheenjohtaja ehdotti, että äänestys suoritetaan nimenhuutoäänestyksenä siten, että esittelijän ehdotusta kannattavat äänestävät ”jaa” ja Lehtosen muutosehdotusta kannattavat äänestävät ”ei”.",
        "Äänestyksessä esittelijän ehdotusta (jaa) kannattivat Mika Kauste, Pauliina Ilkko-Ervasti, Pia Palojärvi, Mirjami Tuomikoski, Kim Ahlfors, Aulikki Pentikäinen, Tiina Ahlroos ja Mika Hentunen, yhteensä kahdeksan (8) ääntä.",
        "Lehtosen muutosehdotusta (ei) kannattivat Jussi Lehtonen ja Anna Virtanen, yhteensä kaksi ääntä.",
    )
    assert counts(v)[:2] == (8, 2) and len(v.ballots) == 10


def test_result_with_its_winner():
    [v] = votes(
        "Puheenjohtaja totesi, että EI äänet voittivat ja palautusehdotus voitti äänin kuusi (6) – viisi (5)."
    )
    assert counts(v)[:2] == (5, 6) and not v.needs_review
    [v] = votes(
        "Perokorven esitys voitti kaupunginjohtajan esityksen äänin 8 (Lybeck Robin, Valasti Matti, Hjelt Nea, Ahonen Noora, Ryynänen Sami, Riikonen Jere, Jokisaari Milla, Perokorpi Jenna) 5 (Sigfrids Frida, Lund Bodil, Nylander Mikaela, Holmström Johnny, Söderberg Johan)."
    )
    assert counts(v)[:2] == (8, 5) and len(v.ballots) == 13 and not v.needs_review
    assert v.jaa_label == "Perokorven esitys" and v.ei_label == "Kaupunginjohtajan esityksen"


def test_choice_word_before_its_count():
    [v] = votes("Äänestyksessä annettiin JAA ääniä 3 ja EI ääniä 7.")
    assert counts(v)[:2] == (3, 7)


def test_tie_written_as_tasan():
    [v] = votes("Äänestyksessä äänten mennessä tasan 5-5 ja 3 tyhjää, ratkaisi puheenjohtajan ääni.")
    assert sorted(counts(v)[:2]) == [5, 5]


def test_lowercase_name_particle():
    [v] = votes(
        "Äänestyksen tulos:\n3 JAA-ääntä (Lintula, van Schevikhoven, Virtanen)\n2 EI-ääntä (Mäki, Koski)"
    )
    assert names(v, Choice.jaa) == ["Lintula", "van Schevikhoven", "Virtanen"]
    assert not v.needs_review
