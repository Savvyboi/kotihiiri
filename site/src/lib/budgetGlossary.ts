// Plain-language explanations of the budget lines and the questions residents ask, in the three
// site languages (PLAN.md §19.1). Kept here rather than in the i18n dictionaries because they are
// prose, not interface text.
import type { Locale } from '../i18n';

type Text = Record<Locale, string>;

/** What a budget line means, keyed by its line key in data/talous/items.json. */
export const EXPLAIN: Record<string, Text> = {
  toimintatulot: {
    fi: 'Tulot, jotka kunta saa omasta toiminnastaan: myynnit, asiakasmaksut, saadut tuet ja vuokrat. Verot ja valtionosuudet eivät kuulu tähän.',
    sv: 'Inkomster som kommunen får från sin egen verksamhet: försäljning, avgifter, bidrag och hyror. Skatter och statsandelar ingår inte.',
    en: 'Money the municipality earns from its own activities: sales, fees, grants and rents. Taxes and central government transfers are not included.',
  },
  myyntitulot: {
    fi: 'Palveluista ja tavaroista, joita kunta myy toisille: esimerkiksi vesi- ja jätehuolto, palvelut naapurikunnille ja hyvinvointialueelle.',
    sv: 'Tjänster och varor som kommunen säljer till andra, till exempel vatten och avfall, tjänster till grannkommuner och välfärdsområdet.',
    en: 'Services and goods the municipality sells to others, such as water and waste services, or services sold to neighbouring municipalities and the wellbeing services county.',
  },
  maksutulot: {
    fi: 'Asukkaiden maksamat asiakasmaksut, esimerkiksi varhaiskasvatuksen, kirjaston ja liikuntapaikkojen maksut sekä luvat.',
    sv: 'Avgifter som invånarna betalar, till exempel för småbarnspedagogik, bibliotek, idrottsplatser och tillstånd.',
    en: 'Fees residents pay, for example for early childhood education, libraries, sports facilities and permits.',
  },
  'tuet-ja-avustukset': {
    fi: 'Valtiolta, EU:lta ja muilta saadut kohdennetut avustukset tiettyyn toimintaan, esimerkiksi työllisyyshankkeisiin. Eivät ole valtionosuuksia.',
    sv: 'Riktade bidrag från staten, EU och andra för en viss verksamhet, till exempel sysselsättningsprojekt. Inte statsandelar.',
    en: 'Grants from the state, the EU and others for a specific purpose, such as employment projects. Separate from central government transfers.',
  },
  'muut-toimintatulot': {
    fi: 'Suurimmaksi osaksi vuokratuloja kunnan omistamista tiloista ja maasta sekä maanmyyntien voittoja.',
    sv: 'Mest hyresinkomster från kommunens lokaler och mark samt vinster från markförsäljning.',
    en: 'Mostly rent from buildings and land the municipality owns, and gains from land sales.',
  },
  toimintamenot: {
    fi: 'Kaikki kunnan palvelujen pyörittämisen kulut vuoden aikana: palkat, ostetut palvelut, tarvikkeet, avustukset ja vuokrat.',
    sv: 'Alla kostnader för att driva kommunens tjänster under året: löner, köpta tjänster, material, bidrag och hyror.',
    en: 'Everything it costs to run the municipality’s services during the year: wages, purchased services, supplies, grants and rents.',
  },
  henkilostomenot: {
    fi: 'Kunnan työntekijöiden palkat ja niiden sivukulut, kuten eläke- ja sosiaaliturvamaksut. Suurin osa menee opetukseen ja varhaiskasvatukseen.',
    sv: 'Löner till kommunens anställda och lönebikostnader som pensions- och socialskyddsavgifter. Största delen går till undervisning och småbarnspedagogik.',
    en: 'Wages of the municipality’s staff and related costs such as pension and social security contributions. Most goes to schools and early childhood education.',
  },
  'palvelujen-ostot': {
    fi: 'Palvelut, jotka kunta ostaa yrityksiltä, järjestöiltä tai toisilta kunnilta, esimerkiksi rakentaminen ja kunnossapito, joukkoliikenne ja ostetut koulupaikat.',
    sv: 'Tjänster som kommunen köper av företag, organisationer eller andra kommuner, till exempel byggande och underhåll, kollektivtrafik och köpta skolplatser.',
    en: 'Services the municipality buys from companies, associations or other municipalities, for example construction and maintenance, public transport and school places.',
  },
  'aineet-tarvikkeet-ja-tavarat': {
    fi: 'Ostetut tavarat: kouluruoan raaka-aineet, opetusmateriaalit, energia, polttoaineet ja muut tarvikkeet.',
    sv: 'Köpta varor: råvaror till skolmat, läromedel, energi, bränsle och andra förnödenheter.',
    en: 'Goods bought: ingredients for school meals, teaching materials, energy, fuel and other supplies.',
  },
  avustukset: {
    fi: 'Kunnan maksamat avustukset kotitalouksille ja yhteisöille, esimerkiksi kotihoidon tuen kuntalisä, työmarkkinatuen kuntaosuus sekä järjestöjen ja seurojen avustukset.',
    sv: 'Bidrag som kommunen betalar till hushåll och organisationer, till exempel kommuntillägg till hemvårdsstöd, kommunens andel av arbetsmarknadsstödet och bidrag till föreningar.',
    en: 'Grants the municipality pays to households and organisations, such as supplements to child home care allowance, its share of labour market support, and grants to clubs and associations.',
  },
  'muut-toimintamenot': {
    fi: 'Enimmäkseen vuokrat, joita kunta maksaa käyttämistään tiloista, sekä muita pieniä eriä.',
    sv: 'Mest hyror för lokaler som kommunen använder och andra mindre poster.',
    en: 'Mostly rent the municipality pays for premises it uses, and other small items.',
  },
  'valmistus-omaan-kayttoon': {
    fi: 'Kunnan oma työ omiin investointeihinsa, esimerkiksi oman rakennusyksikön tekemät työt. Se on mukana menoissa, mutta kirjataan investoinniksi, joten se vähennetään käyttömenoista.',
    sv: 'Kommunens eget arbete för sina egna investeringar. Det ingår i utgifterna men bokförs som investering och dras därför av från driftskostnaderna.',
    en: 'Work the municipality does on its own investments, such as building by its own crews. It is in the expenses but booked as investment, so it is deducted from running costs.',
  },
  toimintakate: {
    fi: 'Toimintatulot miinus toimintamenot. Lähes aina negatiivinen: se osa palveluista, joka on rahoitettava verotuloilla ja valtionosuuksilla.',
    sv: 'Verksamhetsinkomster minus verksamhetsutgifter. Nästan alltid negativt: den del av tjänsterna som ska finansieras med skatter och statsandelar.',
    en: 'Operating income minus operating expenses. Almost always negative: the part of the services that must be paid for with taxes and central government transfers.',
  },
  verotulot: {
    fi: 'Kunnallisvero asukkaiden tuloista, osuus yhteisöverosta (yritysten voitoista) ja kiinteistövero. Kunnan suurin tulolähde.',
    sv: 'Kommunalskatt på invånarnas inkomster, andel av samfundsskatten (företagens vinster) och fastighetsskatt. Kommunens största inkomstkälla.',
    en: 'Municipal income tax on residents’ earnings, a share of corporate tax, and property tax. The municipality’s largest source of money.',
  },
  valtionosuudet: {
    fi: 'Valtion rahoitus peruspalveluihin, kuten opetukseen ja kulttuuriin. Määrä riippuu mm. asukkaiden ikärakenteesta ja kunnan verotulojen tasosta.',
    sv: 'Statens finansiering av basservice som undervisning och kultur. Beloppet beror bland annat på invånarnas ålder och kommunens skatteinkomster.',
    en: 'State funding for basic services such as schools and culture. The amount depends on things like the age structure of residents and the municipality’s own tax base.',
  },
  'rahoitustulot-ja-menot': {
    fi: 'Korkotulot, osingot ja omistusten tuotot miinus korkomenot. Positiivinen, jos kunnan omistukset (esim. energiayhtiö) tuottavat enemmän kuin lainat maksavat.',
    sv: 'Ränteintäkter, dividender och avkastning minus räntekostnader. Positivt om kommunens ägande (t.ex. ett energibolag) ger mer än lånen kostar.',
    en: 'Interest income, dividends and returns on holdings minus interest paid. Positive when what the municipality owns (an energy company, say) earns more than its loans cost.',
  },
  vuosikate: {
    fi: 'Mitä tuloista jää käteen, kun käyttömenot on maksettu. Tällä rahoitetaan investoinnit ja lainojen lyhennykset. Kuntatalous on terveellä pohjalla, kun vuosikate riittää vähintään poistoihin.',
    sv: 'Det som blir kvar av inkomsterna när driftskostnaderna är betalda. Med det finansieras investeringar och amorteringar. Ekonomin är sund när årsbidraget täcker minst avskrivningarna.',
    en: 'What is left of income once running costs are paid. It pays for investments and loan repayments. Municipal finances are on a sound footing when the annual margin at least covers depreciation.',
  },
  'poistot-ja-arvonalentumiset': {
    fi: 'Rakennusten, katujen ja laitteiden kuluminen vuoden aikana. Kertoo suunnilleen, paljonko pitäisi investoida vuosittain, jotta omaisuus pysyy ennallaan.',
    sv: 'Hur byggnader, gator och utrustning slits under året. Ungefär hur mycket som borde investeras varje år för att egendomen ska hållas i skick.',
    en: 'How much buildings, streets and equipment wear out during the year: roughly what must be invested each year just to keep assets as they are.',
  },
  'satunnaiset-erat': {
    fi: 'Kertaluonteiset, tavanomaisesta toiminnasta poikkeavat tulot ja menot.',
    sv: 'Engångsinkomster och -utgifter som avviker från den normala verksamheten.',
    en: 'One-off income and costs outside normal activities.',
  },
  'tilikauden-tulos': {
    fi: 'Vuosikate miinus poistot. Positiivinen tulos tarkoittaa, että tulot riittävät palveluihin ja omaisuuden kulumiseen.',
    sv: 'Årsbidrag minus avskrivningar. Ett positivt resultat betyder att inkomsterna räcker till tjänsterna och till att täcka slitaget på egendomen.',
    en: 'Annual margin minus depreciation. A positive result means income covers both services and the wear on assets.',
  },
  tilinpaatossiirrot: {
    fi: 'Kirjanpidolliset siirrot rahastoihin ja varauksiin tai niistä.',
    sv: 'Bokföringsmässiga överföringar till eller från fonder och reserver.',
    en: 'Book-keeping transfers to or from funds and reserves.',
  },
  'tilikauden-ylijaama-alijaama': {
    fi: 'Lopullinen yli- tai alijäämä. Kuntalain mukaan taseeseen kertynyt alijäämä on katettava muutaman vuoden kuluessa, tai kunta voi joutua arviointimenettelyyn.',
    sv: 'Slutligt överskott eller underskott. Enligt kommunallagen ska ett ackumulerat underskott täckas inom några år, annars kan kommunen bli föremål för ett utvärderingsförfarande.',
    en: 'The final surplus or deficit. Under the Local Government Act a deficit built up on the balance sheet must be covered within a few years, or the state may start a review of the municipality.',
  },
  'investointimenot-yhteensa-brutto': {
    fi: 'Rahat, jotka käytetään pitkäikäiseen omaisuuteen: koulujen ja päiväkotien rakentamiseen, katuihin, puistoihin, maahan ja laitteisiin.',
    sv: 'Pengar som går till långlivad egendom: skolor och daghem, gator, parker, mark och utrustning.',
    en: 'Money spent on things that last for years: schools and day-care centres, streets, parks, land and equipment.',
  },
  rakennukset: {
    fi: 'Uudet rakennukset ja vanhojen peruskorjaukset.',
    sv: 'Nya byggnader och grundliga renoveringar av gamla.',
    en: 'New buildings and major renovations of existing ones.',
  },
  'rakennukset-opetus-ja-kulttuuritoimi': {
    fi: 'Koulut, päiväkodit, kirjastot ja muut opetuksen ja kulttuurin rakennukset.',
    sv: 'Skolor, daghem, bibliotek och andra byggnader för undervisning och kultur.',
    en: 'Schools, day-care centres, libraries and other buildings for education and culture.',
  },
  'rakennukset-sosiaali-ja-terveystoimi': {
    fi: 'Sosiaali- ja terveyspalvelujen rakennukset. Vuodesta 2023 palvelut ovat hyvinvointialueiden, mutta kunta voi yhä omistaa ja vuokrata tiloja.',
    sv: 'Byggnader för social- och hälsovård. Sedan 2023 ansvarar välfärdsområdena för tjänsterna, men kommunen kan fortfarande äga och hyra ut lokaler.',
    en: 'Buildings for social and health services. Since 2023 those services belong to the wellbeing services counties, but municipalities may still own and rent out the premises.',
  },
  'rakennukset-muut': {
    fi: 'Muut rakennukset, kuten liikuntahallit, virastotalot ja asunnot.',
    sv: 'Andra byggnader, som idrottshallar, ämbetshus och bostäder.',
    en: 'Other buildings, such as sports halls, offices and housing.',
  },
  'kiinteat-rakenteet-ja-laitteet': {
    fi: 'Kadut, tiet, sillat, puistot, vesi- ja viemäriverkostot sekä muu kunnallistekniikka.',
    sv: 'Gator, vägar, broar, parker, vatten- och avloppsnät och annan kommunalteknik.',
    en: 'Streets, roads, bridges, parks, water and sewer networks and other infrastructure.',
  },
  'maa-ja-vesialueet': {
    fi: 'Maan ostot, usein tulevaa kaavoitusta ja rakentamista varten.',
    sv: 'Markköp, ofta för kommande planläggning och byggande.',
    en: 'Land purchases, often for future zoning and building.',
  },
  'koneet-ja-kalusto': {
    fi: 'Ajoneuvot, koneet, kalusteet ja tietotekniikka.',
    sv: 'Fordon, maskiner, inventarier och IT-utrustning.',
    en: 'Vehicles, machinery, furniture and IT equipment.',
  },
  'aineettomat-hyodykkeet': {
    fi: 'Esimerkiksi tietojärjestelmät, ohjelmistot ja käyttöoikeudet.',
    sv: 'Till exempel informationssystem, programvara och nyttjanderätter.',
    en: 'For example information systems, software and rights of use.',
  },
  'muut-aineelliset-hyodykkeet': {
    fi: 'Muu pitkäikäinen omaisuus, kuten taide-esineet.',
    sv: 'Annan långlivad egendom, som konstverk.',
    en: 'Other long-lived assets, such as works of art.',
  },
  'osakkeet-ja-osuudet': {
    fi: 'Pääomasijoitukset kunnan yhtiöihin ja kuntayhtymiin, esimerkiksi asunto- tai energiayhtiöön.',
    sv: 'Kapitalplaceringar i kommunens bolag och samkommuner, till exempel ett bostads- eller energibolag.',
    en: 'Capital put into the municipality’s companies and joint authorities, such as a housing or energy company.',
  },
  'rahoitusosuudet-investointimenoihin': {
    fi: 'Valtion, EU:n tai muiden osuudet kunnan investointien kustannuksiin.',
    sv: 'Statens, EU:s eller andras andelar av kommunens investeringskostnader.',
    en: 'Contributions from the state, the EU or others towards the municipality’s investments.',
  },
  'investointihyodykkeiden-luovutustulot-brutto': {
    fi: 'Tulot maan, rakennusten ja osakkeiden myynnistä.',
    sv: 'Inkomster från försäljning av mark, byggnader och aktier.',
    en: 'Money from selling land, buildings and shares.',
  },
  'toiminnan-ja-investointien-rahavirta': {
    fi: 'Vuosikate ja omaisuuden myynnit miinus investoinnit. Negatiivinen luku on se, mikä on katettava lainalla tai kassavaroilla.',
    sv: 'Årsbidrag och försäljning av egendom minus investeringar. Ett negativt tal måste täckas med lån eller kassamedel.',
    en: 'Annual margin plus asset sales, minus investments. A negative figure has to be covered by borrowing or cash reserves.',
  },
  'lainakanta-31-12': {
    fi: 'Kunnan lainat vuoden lopussa. Ei sisällä kunnan yhtiöiden lainoja eikä kunnan niille antamia takauksia.',
    sv: 'Kommunens lån vid årets slut. Omfattar inte lån i kommunens bolag eller borgen kommunen gett för dem.',
    en: 'The municipality’s loans at the end of the year. Excludes loans of its companies and guarantees it has given them.',
  },
  henkilotyovuodet: {
    fi: 'Kunnan työpanos kokoaikaisiksi vuosityöntekijöiksi muunnettuna.',
    sv: 'Kommunens arbetsinsats omräknad till heltidsanställda per år.',
    en: 'The municipality’s workforce as full-time equivalents for the year.',
  },
  tuloveroprosentti: {
    fi: 'Kunnallisveroprosentti, jonka kunta perii asukkaidensa ansiotuloista.',
    sv: 'Kommunalskattesatsen som kommunen tar ut på invånarnas förvärvsinkomster.',
    en: 'The municipal income tax rate the municipality levies on residents’ earned income.',
  },
};

/** Net financial items shown as one income or cost part. */
export const FIN_LABEL: Record<'finIncome' | 'finCost', Text> = {
  finIncome: { fi: 'Rahoitustuotot (netto)', sv: 'Finansiella intäkter (netto)', en: 'Financial income (net)' },
  finCost: { fi: 'Korot ja muut rahoituskulut (netto)', sv: 'Räntor och andra finansiella kostnader (netto)', en: 'Interest and other financial costs (net)' },
};

/** Questions residents ask about a municipal budget. `{city}` is the municipality's name. */
export const FAQ: { q: Text; a: Text }[] = [
  {
    q: { fi: 'Mikä talousarvio on?', sv: 'Vad är en budget?', en: 'What is a municipal budget?' },
    a: {
      fi: 'Talousarvio on valtuuston päätös siitä, paljonko kunta saa seuraavana vuonna käyttää rahaa ja mistä rahat tulevat. Samalla hyväksytään taloussuunnitelma kahdelle seuraavalle vuodelle. Kunnanhallitus valmistelee talousarvion syksyllä ja valtuusto hyväksyy sen yleensä joulukuussa.',
      sv: 'Budgeten är fullmäktiges beslut om hur mycket pengar kommunen får använda nästa år och varifrån pengarna kommer. Samtidigt godkänns en ekonomiplan för de två följande åren. Kommunstyrelsen bereder budgeten på hösten och fullmäktige godkänner den i regel i december.',
      en: 'The budget is the council’s decision on how much the municipality may spend next year and where the money comes from. A financial plan for the two following years is approved with it. The executive board prepares it in the autumn and the council usually approves it in December.',
    },
  },
  {
    q: { fi: 'Onko talousarvio sama kuin toteutunut talous?', sv: 'Är budgeten samma sak som utfallet?', en: 'Is the budget what was actually spent?' },
    a: {
      fi: 'Ei. Nämä ovat hyväksyttyjä arvioita. Toteutuneet luvut julkaistaan tilinpäätöksessä seuraavana keväänä, ja ne poikkeavat usein talousarviosta. Valtuusto voi myös muuttaa talousarviota kesken vuoden; sarake "muutoksineen" sisältää nämä muutokset.',
      sv: 'Nej. Detta är godkända uppskattningar. Utfallet publiceras i bokslutet följande vår och avviker ofta från budgeten. Fullmäktige kan också ändra budgeten under året; kolumnen "med ändringar" innehåller dem.',
      en: 'No. These are approved estimates. Actual figures come in the financial statements the following spring and often differ. The council can also amend the budget during the year; the “with amendments” column includes those changes.',
    },
  },
  {
    q: { fi: 'Miksi luvuissa ei ole terveydenhuoltoa?', sv: 'Varför syns inte hälso- och sjukvården?', en: 'Why is there no healthcare spending?' },
    a: {
      fi: 'Vuoden 2023 alusta sosiaali- ja terveyspalvelut ja pelastustoimi siirtyivät hyvinvointialueille (Helsingissä kaupungille itselleen, mutta erilliseen talousarvioon). Siksi kuntien menot ja verotulot pienenivät selvästi vuodesta 2022 vuoteen 2023, eivätkä vuodet ole suoraan verrattavissa.',
      sv: 'Från början av 2023 flyttades social- och hälsovården och räddningsväsendet till välfärdsområdena (i Helsingfors till staden själv, men i en separat budget). Därför minskade kommunernas utgifter och skatteinkomster kraftigt mellan 2022 och 2023, och åren är inte direkt jämförbara.',
      en: 'From the start of 2023 social and health services and rescue services moved to the new wellbeing services counties (in Helsinki to the city itself, but in a separate budget). Municipal spending and tax revenue therefore fell sharply from 2022 to 2023, and those years are not directly comparable.',
    },
  },
  {
    q: { fi: 'Miksi menoja ei näytetä toimialoittain?', sv: 'Varför visas inte utgifterna per sektor?', en: 'Why is spending not shown by department?' },
    a: {
      fi: 'Kunnat ilmoittavat talousarvionsa Valtiokonttorille yhtenäisellä lomakkeella, jossa menot jaetaan lajeittain (palkat, ostot, avustukset) mutta ei toimialoittain. Toimialoittaiset määrärahat, kuten opetus tai kulttuuri, löytyvät kunnan omasta talousarviokirjasta, johon pääset kunnan sivuilta.',
      sv: 'Kommunerna rapporterar sin budget till Statskontoret på ett enhetligt formulär där utgifterna delas upp efter slag (löner, köp, bidrag) men inte per sektor. Anslagen per sektor, som undervisning eller kultur, finns i kommunens egen budgetbok på kommunens webbplats.',
      en: 'Municipalities report their budgets to the State Treasury on a common form that splits spending by type (wages, purchases, grants) but not by department. Allocations by department, such as education or culture, are in the municipality’s own budget book on its website.',
    },
  },
  {
    q: { fi: 'Miten asukaskohtaiset luvut lasketaan?', sv: 'Hur räknas beloppen per invånare?', en: 'How are the per-resident figures worked out?' },
    a: {
      fi: 'Euromäärä jaetaan kunnan nykyisellä asukasluvulla Tilastokeskuksen tiedoista. Vanhempien vuosien luvut ovat siksi suuntaa antavia. Vertailu muihin kuntiin käyttää saman vuoden talousarvioita kaikista kunnista, joiden luvut ovat saatavilla.',
      sv: 'Beloppet delas med kommunens nuvarande invånarantal enligt Statistikcentralen. Siffrorna för äldre år är därför ungefärliga. Jämförelsen med andra kommuner använder samma års budgetar för alla kommuner med uppgifter.',
      en: 'The amount is divided by the municipality’s current population from Statistics Finland, so figures for older years are approximate. The comparison with other municipalities uses the same year’s budgets of every municipality with data.',
    },
  },
  {
    q: { fi: 'Mistä luvut tulevat ja voinko käyttää niitä?', sv: 'Var kommer siffrorna ifrån och får jag använda dem?', en: 'Where do the figures come from, and can I reuse them?' },
    a: {
      fi: 'Luvut ovat Valtiokonttorin kuntien taloustietopalvelusta, johon kunta itse ilmoittaa hyväksytyn talousarvionsa. Ne ovat avointa dataa (CC BY 4.0): voit ladata ne alta CSV-tiedostona ja käyttää vapaasti, kun mainitset lähteen.',
      sv: 'Siffrorna kommer från Statskontorets ekonomiska informationstjänst, dit kommunen själv rapporterar sin godkända budget. De är öppna data (CC BY 4.0): ladda ner dem nedan som CSV och använd dem fritt med källhänvisning.',
      en: 'They come from the State Treasury’s municipal finance service, to which each municipality reports its approved budget. They are open data (CC BY 4.0): download them below as CSV and reuse them freely with attribution.',
    },
  },
];
