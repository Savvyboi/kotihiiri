"""Generate the fictional demo dataset in site/demo-data (deterministic)."""

import datetime as dt
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kunta import jsonio
from kunta.ids import body_id, item_id, meeting_file_path, meeting_id
from kunta.models import *
from kunta.text import content_sha256

OUT = ROOT / "site" / "demo-data"
rng = random.Random(2025)
FIRST = [
    "Aino",
    "Eero",
    "Helmi",
    "Ilmari",
    "Kerttu",
    "Lauri",
    "Mikko",
    "Noora",
    "Oona",
    "Pekka",
    "Riikka",
    "Sami",
    "Tuula",
    "Veikko",
    "Wilma",
    "Aleksi",
    "Elina",
    "Juho",
    "Laura",
    "Matias",
]
LAST = [
    "Esimerkki",
    "Kuvitteellinen",
    "Mallinen",
    "Testaaja",
    "Harjoitus",
    "Näyte",
    "Malli",
    "Kokeilu",
    "Luonnos",
    "Demonen",
]
GROUPS = [
    ("Kok.", 22),
    ("Vihr.", 19),
    ("SDP", 15),
    ("Vas.", 10),
    ("PS", 7),
    ("RKP", 6),
    ("KD", 3),
    ("Kesk.", 3),
]


def people(n):
    out, seen = [], set()
    while len(out) < n:
        nm = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        if nm not in seen:
            seen.add(nm)
            out.append(nm)
    return out


def ref(n):
    return PersonRef(raw=n)


def sec(t, txt, h=None):
    return Section(type=t, text=txt, heading=h)


def item(mid, n, pyk, title, decision, proposal, background, votes=(), motions=(), history=None, case=None):
    secs = [sec("decision", decision), sec("proposal", proposal), sec("background", background)]
    if history:
        secs.append(sec("history", history[1], history[0]))
    return AgendaItem(
        id=item_id(mid, n),
        meeting_id=mid,
        ordinal=n,
        pykala=pyk,
        title=title,
        case_number=case,
        presenter="Kaupunginjohtaja (esimerkki)",
        sections=secs,
        motions=list(motions),
        votes=list(votes),
        decision_summary=decision,
        source_url="https://example.org/esimerkki",
        content_sha256=content_sha256(title, decision, proposal, background),
    )


def write(mf, city):
    jsonio.write(OUT / meeting_file_path(mf.meeting.id), mf)


def council_vote(members, jaa_label, ei_label, lean):
    ballots = []
    for name, g in members:
        if rng.random() < 0.04:
            ch = "poissa"
        else:
            p = lean.get(g, 0.5)
            r = rng.random()
            ch = "jaa" if r < p else ("tyhja" if r > 0.97 else "ei")
        ballots.append(Ballot(person_ref=ref(name), choice=ch, group_text=g))
    counts = Counts(**{c: sum(b.choice == c for b in ballots) for c in ("jaa", "ei", "tyhja", "poissa")})
    res = jaa_label if counts.jaa > counts.ei else ei_label
    return VoteEvent(
        ordinal=1,
        jaa_label=jaa_label,
        ei_label=ei_label,
        counts=counts,
        ballots=ballots,
        result_text=f"Kaupunginvaltuusto hyväksyi: {res}",
        source="html",
        source_url="https://example.org/esimerkki",
    )


(OUT).mkdir(parents=True, exist_ok=True)
(OUT / "DEMO").write_text("Fictional demo data for site previews. Not real council data.\n")

BODIES = {
    "helsinki": [
        ("Kaupunginvaltuusto", "council"),
        ("Kaupunginhallitus", "board"),
        ("Kaupunkiympäristölautakunta", "committee"),
        ("Kasvatus- ja koulutuslautakunta", "committee"),
        ("Tarkastuslautakunta", "committee"),
    ],
    "espoo": [
        ("Valtuusto", "council"),
        ("Kaupunginhallitus", "board"),
        ("Kaupunkisuunnittelulautakunta", "committee"),
        ("Tekninen lautakunta", "committee"),
    ],
    "tampere": [
        ("Kaupunginvaltuusto", "council"),
        ("Kaupunginhallitus", "board"),
        ("Asunto- ja kiinteistölautakunta", "committee"),
    ],
    "vantaa": [
        ("Kaupunginvaltuusto", "council"),
        ("Kaupunginhallitus", "board"),
        ("Kaupunkiympäristölautakunta", "committee"),
    ],
}
for city, bl in BODIES.items():
    bodies = [Body(id=body_id(city, n), city=city, name_fi=n, kind=k) for n, k in bl]
    jsonio.write(OUT / city / "bodies.json", bodies)


def council_members(n=85):
    names = people(n)
    out = []
    i = 0
    for g, k in GROUPS:
        for _ in range(k):
            out.append((names[i], g))
            i += 1
    return out


TOPICS = [
    (
        "Raitiotien jatkaminen keskustasta uudelle asuinalueelle",
        "Valtuusto hyväksyi hankesuunnitelman ja enimmäishinnan.",
        {
            "Kok.": 0.85,
            "Vihr.": 0.95,
            "SDP": 0.7,
            "Vas.": 0.6,
            "PS": 0.1,
            "RKP": 0.8,
            "KD": 0.3,
            "Kesk.": 0.4,
        },
    ),
    (
        "Kouluverkon uudistus ja kahden koulurakennuksen peruskorjaus",
        "Valtuusto hyväksyi esityksen äänin.",
        {"Kok.": 0.9, "Vihr.": 0.3, "SDP": 0.5, "Vas.": 0.1, "PS": 0.6, "RKP": 0.8, "KD": 0.6, "Kesk.": 0.7},
    ),
    (
        "Asemakaavan muutos rantakortteliin (kuvitteellinen alue)",
        "Valtuusto hyväksyi asemakaavan muutoksen.",
        None,
    ),
    (
        "Valtuustoaloite kaupunkipyöräkauden pidentämisestä",
        "Valtuusto merkitsi aloitteen vastauksen tiedoksi.",
        None,
    ),
    ("Tilintarkastajan valinta vuosille 2026–2027", "Valtuusto valitsi tilintarkastusyhteisön.", None),
]


def make_city(city, council_name, dates, groups=True, upcoming=None):
    cb = body_id(city, council_name)
    members = council_members()
    for di, d in enumerate(dates):
        mid = meeting_id(cb, d)
        items = []
        for n, (title, dec, lean) in enumerate(TOPICS[di % 2 : di % 2 + 4], start=1):
            votes, motions = [], []
            if lean:
                v = council_vote(members, "Esittelijän ehdotus", "Valtuutetun vastaehdotus", lean)
                if not groups:
                    v = v.model_copy(
                        update={
                            "ballots": [b.model_copy(update={"group_text": None}) for b in v.ballots],
                            "source": "pdf",
                        }
                    )
                votes = [v]
                motions = [
                    Motion(
                        kind="counter_proposal",
                        proposer_ref=ref(members[30][0]),
                        seconder_refs=[ref(members[50][0])],
                        text="Esitän, että asia palautetaan uudelleen valmisteltavaksi ja vaihtoehdot selvitetään. (Esimerkkiteksti.)",
                        outcome="rejected" if v.counts.jaa > v.counts.ei else "adopted",
                    )
                ]
            items.append(
                item(
                    mid,
                    n,
                    200 + di * 10 + n,
                    title,
                    dec,
                    "Kaupunginhallitus esittää, että valtuusto hyväksyy asian liitteen mukaisesti. (Esimerkkiteksti.)",
                    "Tämä on keksitty perusteluteksti esikatselua varten. Oikeassa aineistossa tähän tulee esittelijän perustelut kokonaisuudessaan.",
                    votes=votes,
                    motions=motions,
                    case=f"ESIM 2026-{1000 + di * 10 + n:06d}",
                    history=(
                        "Kaupunginhallitus 1.9.2026",
                        "Kaupunginhallitus esitti asiaa valtuustolle. (Esimerkkiteksti.)",
                    ),
                )
            )
        att = [
            Attendance(person_ref=ref(nm), role_text="valtuutettu", present=rng.random() > 0.05)
            for nm, _ in members
        ]
        m = Meeting(
            id=mid,
            body_id=cb,
            date=d,
            start_time="18:00",
            end_time="22:15",
            location="Valtuustosali",
            stage="minutes",
            source_url="https://example.org/esimerkki",
            attendance=att,
            items=[i.id for i in items],
            video_url="https://example.org/video",
        )
        write(MeetingFile(meeting=m, items=items), city)
    if upcoming:
        mid = meeting_id(cb, upcoming)
        it = [
            item(
                mid,
                1,
                None,
                "Talousarvio vuodelle 2027 ja taloussuunnitelma",
                "",
                "Kaupunginhallitus esittää talousarvion hyväksymistä. (Esimerkkiteksti.)",
                "Esimerkkiteksti.",
            )
        ]
        it[0] = it[0].model_copy(
            update={"sections": [s for s in it[0].sections if s.type != "decision"], "decision_summary": None}
        )
        write(
            MeetingFile(
                meeting=Meeting(
                    id=mid,
                    body_id=cb,
                    date=upcoming,
                    stage="agenda",
                    source_url="https://example.org/esimerkki",
                    items=[it[0].id],
                ),
                items=it,
            ),
            city,
        )
    # one board meeting without votes
    bb = body_id(city, "Kaupunginhallitus")
    bd = dates[0] - dt.timedelta(days=22)
    mid = meeting_id(bb, bd)
    its = [
        item(
            mid,
            1,
            500,
            "Lausunto maakuntakaavaluonnoksesta",
            "Kaupunginhallitus antoi lausunnon.",
            "Esimerkkiteksti.",
            "Esimerkkiteksti.",
        )
    ]
    write(
        MeetingFile(
            meeting=Meeting(
                id=mid,
                body_id=bb,
                date=bd,
                stage="minutes",
                source_url="https://example.org/esimerkki",
                items=[its[0].id],
            ),
            items=its,
        ),
        city,
    )


make_city(
    "helsinki",
    "Kaupunginvaltuusto",
    [dt.date(2026, 9, 23), dt.date(2026, 9, 9)],
    upcoming=dt.date(2026, 10, 21),
)
make_city("espoo", "Valtuusto", [dt.date(2026, 9, 21)], groups=False, upcoming=dt.date(2026, 10, 19))
make_city("tampere", "Kaupunginvaltuusto", [dt.date(2026, 9, 14)])
make_city("vantaa", "Kaupunginvaltuusto", [dt.date(2026, 9, 28)])


def make_initiatives(city, mid, n, start):
    """Fictional municipal initiatives in the shape `kunta initiatives` writes (no author names)."""
    r = random.Random(f"initiatives-{city}")
    topics = ["koirapuisto", "pyörätie", "uimahalli", "kirjaston aukioloajat", "leikkipuisto", "katuvalot"]
    recs = []
    for k in range(n):
        i = start + k
        pub = dt.date(2026, 9, 30) - dt.timedelta(days=11 * k)
        sent = pub + dt.timedelta(days=r.randint(5, 60)) if k > 2 and r.random() < 0.6 else None
        rec = {
            "id": i,
            "name": f"Esimerkkialoite: {topics[k % len(topics)]} ({k + 1})",
            "type": "SINGLE" if k % 4 == 0 else "COLLABORATIVE",
            "collaborative": k % 4 != 0,
            "publish_date": pub.isoformat(),
            "participants": 0 if k % 4 == 0 else r.randint(1, 400),
            "url_fi": f"https://www.kuntalaisaloite.fi/fi/aloite/{i}",
            "url_sv": f"https://www.kuntalaisaloite.fi/sv/initiativ/{i}",
            "proposal": "Esimerkkiteksti. Ehdotamme, että kunta selvittää asian ja ryhtyy toimiin.",
            "authors": 1 + k % 3,
        }
        if sent:
            rec["sent_date"] = sent.isoformat()
        recs.append(rec)
    jsonio.write(
        OUT / "initiatives" / f"{city}.json",
        {
            "municipality": city,
            "source": "https://www.kuntalaisaloite.fi/api",
            "source_municipality_id": mid,
            "active_in_service": True,
            "initiatives": sorted(recs, key=lambda x: -x["id"]),
        },
    )


make_initiatives("helsinki", 91, 12, 9000)
make_initiatives("espoo", 49, 5, 8000)
print("ok")
