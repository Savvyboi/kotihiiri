# Finnish city decisions site — implementation plan

> **For the coding agent.** This is the build spec. Work milestone by milestone (§15), in order. Each task has acceptance criteria; a milestone is done only when all of them pass. Anything marked **UNVERIFIED** must be checked with a short discovery spike before you write the parser, and the result written back into this file (§16). Hard constraints in §2 are non-negotiable — if a task seems to require breaking one, stop and ask a human.

Last research pass: 2026-10-11. URLs and page structures below were checked by hand on that date.

---

## 0. Glossary (Finnish → meaning in this codebase)

| Finnish | Meaning | Field / enum |
|---|---|---|
| kaupunginvaltuusto (kvsto) | city council | `body.kind = council` |
| kaupunginhallitus (kh) | city board (executive) | `body.kind = board` |
| lautakunta | committee | `body.kind = committee` |
| jaosto | section / sub-committee of a board or committee | `body.kind = section` |
| johtokunta | board of a municipal enterprise (liikelaitos) | `body.kind = enterprise_board` |
| tarkastuslautakunta | audit committee | `body.kind = committee` |
| esityslista | agenda | `meeting.stage = agenda` |
| päätöstiedote | decision bulletin (Helsinki, right after meeting) | `meeting.stage = decisions` |
| pöytäkirja | minutes (final, legally published) | `meeting.stage = minutes` |
| asia / asiakohta | agenda item | `AgendaItem` |
| pykälä (§) | minutes paragraph number (running per body per year) | `item.pykala` |
| diaarinumero / asianumero | case number, links an issue across bodies | `item.case_number` |
| päätösehdotus | proposal | section `proposal` |
| käsittely | deliberation (motions, votes) | section `deliberation` |
| päätös | decision | section `decision` |
| perustelut / selostus | background / reasoning | section `background` |
| päätöshistoria / aikaisempi käsittely | earlier handling in other bodies | section `history` |
| vastaehdotus | counter-proposal | `motion.kind = counter_proposal` |
| palautusehdotus | motion to send back for re-preparation | `motion.kind = send_back` |
| pöydällepanoehdotus | motion to table | `motion.kind = table` |
| toivomusponsi | resolution / rider attached to a decision | `motion.kind = resolution` |
| kannattaja | seconder | `motion.seconders` |
| äänestys | vote | `VoteEvent` |
| Jaa / Ei / Tyhjä / Poissa | yes / no / blank (abstain) / absent | `ballot.choice` |
| valtuustoryhmä | council group (≈ party group) | `Membership.group` |
| varajäsen | deputy member | `Membership.role = deputy` |
| esittelijä | presenting official | `item.presenter` |
| pöytäkirjalausuma | statement entered in minutes | section `statement` |
| eriävä mielipide | dissenting opinion | section `dissent` |
| esteellinen | disqualified (conflict of interest) | `item.disqualified[]` |
| keskustelupöytäkirja / litteraatti | verbatim speech transcript | `Speech` |
| vastauspuheenvuoro / replik | short reply speech | `speech.kind = reply` |
| muutoksenhakuohje / valitusosoitus | appeal instructions (boilerplate) | dropped |

---

## 1. Goal and scope

A static website on GitHub Pages showing what city councils and committees in Finland's six largest cities decide, how members vote and what they say, refreshed by a weekly scraper running in GitHub Actions.

**Decided by the team:**

- **Cities:** Helsinki, Espoo, Tampere, Vantaa, Oulu, Turku. Oulu and Turku ship disabled (see §2.1).
- **Bodies:** council **and** committees. Interpreted as all *decision-making* bodies (päättävät toimielimet):
  - include: council, city board and its sections, committees and their sections, audit committee, municipal-enterprise boards;
  - exclude by default: officeholder decisions (viranhaltijapäätökset), advisory/influence bodies (youth council, elderly council, disability council, multicultural council, area committees, "kehittämistoimikunta", "seurantaryhmä"), election committees (keskusvaalilautakunta, aluevaalilautakunta), test bodies (any name containing "testi", "Testitoimielin", "Versiopäivitystoimielin"), and **bodies that decide individual welfare, student or permit cases** (any "yksilöasioiden jaosto", "lupajaosto", "rakennuslupajaosto", "ympäristö- ja lupajaosto", "oikeusturvatoimielin", "näyttöjen toimielin") because their items are mostly about private individuals.
  - The include/exclude decision lives in `config/bodies/{city}.yaml` so a human can flip it. Default rule in code: include unless the name matches an exclude pattern.
- **Time window:** meetings dated **2025-01-01 or later**. Note: 2025 spans two council terms — the old term ended 31 May 2025 and the new 2025–2029 term began 1 June 2025, and several cities renamed or merged committees at the switch. Bodies that existed only in Jan–May 2025 are in scope.
- **Content:** full item text (all substantive sections), votes with per-member ballots, attendance, motions, speeches where a transcript exists, links to video.

**Out of scope for v1:** speech-to-text of videos, officeholder decisions, mirroring attachments, Swedish-language duplicate documents (Espoo `espoo-sv.oncloudos.com`, Vantaa "Stadsfullmäktige"). *(Swedish and English UI were added on 2026-10-12 at Savvas's request; documents stay untranslated.)*

---

## 2. Hard constraints

### 2.1 Access and politeness
1. **robots.txt is law.** Every adapter checks robots.txt for each host at the start of each run with `urllib.robotparser`, using our User-Agent. If a URL is disallowed, the adapter must not fetch it and must log `skipped_robots`. A unit test enforces this with a fake robots file.
2. **Oulu and Turku are disabled** (`enabled: false` in `config/cities.yaml`, with `reason: robots_disallow_pending_permission`). Both `paatokset.ouka.fi` / `asiakirjat.ouka.fi` and `paatokset.turku.fi` refused automated access on 2026-10-11. Do not write workarounds. Build the Oulu config on the Tweb adapter (same product as Vantaa) so it can be switched on once the city grants permission.
3. User-Agent: `KuntaDataBot/0.1 (+https://<site-domain>/tietoa; <contact-email>)`. Both placeholders come from `config/project.yaml`; refuse to run if they're unset.
4. Max **1 request/second per host**, concurrency 1 per host (different hosts may run in parallel). Exponential backoff on 429/5xx, honour `Retry-After`, give up after 4 attempts and record the failure.
5. Use conditional requests (`If-None-Match` / `If-Modified-Since`) whenever the server returned ETag / Last-Modified.

### 2.2 Data handling
6. **Never commit raw HTML or PDFs.** Raw responses go to `.cache/raw/` (git-ignored, persisted with `actions/cache`). Only normalized JSON is committed.
7. **Never mirror attachments.** Store attachment title + source URL only.
8. **Personal-data minimization.** Finnish municipalities must remove personal data from online minutes after the appeal period. Our copy must follow:
   - drop sections of type `appeal` and `contact`;
   - strip e-mail addresses and phone numbers from all stored text (regex pass; test it);
   - re-fetch recent items (§12) and fully revalidate monthly; if the source removed or changed text, our data changes too; if an item disappears (404/410 twice in a row), write a tombstone and remove it from the site;
   - `config/takedowns.yaml` lists item IDs or literal strings to redact; applied at export/build time.
9. **Speeches by person:** do not build a page that collects all speeches of one person until a human confirms the legal check (Finnish Copyright Act has a specific rule on speeches in public bodies). Feature flag `SPEECHES_BY_PERSON=false`. Speeches are shown in their item/meeting context only.
10. Deterministic output: same input → byte-identical JSON (sorted keys, stable list order, no "fetched_at" inside content files; volatile metadata goes to `data/state/`). A no-change run must produce an empty git diff (except the heartbeat file).

### 2.3 Hosting limits (GitHub Pages)
- Published site ≤ 1 GB, repo recommended ≤ 1 GB, deploy must finish in 10 minutes, soft bandwidth 100 GB/month, non-commercial use only.
- Scheduled workflows in public repos are disabled after 60 days with no repo activity — the councils' summer recess is about that long. Every scheduled run commits `data/state/heartbeat.json`.
- The repo must be public (GitHub Free) unless the org has a paid plan.

---

## 3. Architecture

```
GitHub Actions
 ├─ weekly.yml     crawl (10-week window) → parse → resolve → validate → commit data/ → build → deploy
 ├─ monthly.yml    revalidate everything since 2025-01-01 (conditional GETs) → same tail
 ├─ backfill.yml   workflow_dispatch(city, body, year) → crawl a slice → commit
 └─ smoke.yml      weekly, 1 live request per adapter, opens an issue on layout change

Python package `kunta/` (scraper, CLI)  →  data/*.json (canonical, committed)
                                         →  build/exports/*.parquet,csv (not committed)
Astro site `site/`  reads data/ at build  →  static HTML + Pagefind index  →  GitHub Pages
```

### 3.1 Repository layout

```
.
├── PLAN.md                     # this file
├── AGENTS.md                   # short pointer: "read PLAN.md; constraints in §2"
├── config/
│   ├── project.yaml            # site domain, contact email, user agent
│   ├── cities.yaml             # enabled flag, adapter, base URLs, reasons
│   ├── bodies/{city}.yaml      # discovered bodies + include/exclude overrides
│   └── takedowns.yaml
├── kunta/                      # Python package
│   ├── cli.py                  # typer app
│   ├── http.py                 # polite client: robots, rate limit, cache, retries
│   ├── models.py               # pydantic v2 models (§5)
│   ├── ids.py                  # ID + slug helpers
│   ├── text.py                 # HTML→text, section classification, PII stripping
│   ├── pdf.py                  # pdfplumber helpers, header/footer removal
│   ├── adapters/
│   │   ├── base.py             # Adapter protocol (§6)
│   │   ├── helsinki.py
│   │   ├── dynasty.py          # Espoo
│   │   ├── tweb.py             # Vantaa (+ Oulu later)
│   │   ├── casem.py            # Tampere (CloudNC)
│   │   └── turku.py            # stub, disabled
│   ├── parsers/
│   │   ├── votes_helsinki.py
│   │   ├── votes_cloudmeeting.py   # Espoo "Äänestystulosraportti" PDFs
│   │   ├── speeches_helsinki.py
│   │   └── speeches_vantaa.py
│   ├── people.py               # roster + name resolution (§8)
│   ├── validate.py
│   └── export.py               # parquet/csv exports
├── data/                       # committed, canonical
│   ├── {city}/bodies.json
│   ├── {city}/meetings/{yyyy}/{meeting_slug}.json
│   ├── {city}/speeches/{meeting_slug}.json
│   ├── {city}/people.json
│   ├── review/unresolved_names.csv
│   └── state/{city}.json, heartbeat.json
├── site/                       # Astro project
├── tests/
│   ├── fixtures/{city}/...     # small saved HTML/PDF samples (public documents)
│   └── test_*.py
└── .github/workflows/*.yml
```

### 3.2 Stack (pin these; don't swap without a reason written in this file)
- Python 3.12, `httpx` (sync is fine), `selectolax` (fast HTML) with `beautifulsoup4+lxml` fallback, `pdfplumber`, `pydantic>=2`, `rapidfuzz`, `typer`, `pyyaml`, `orjson`, `pyarrow`, `pytest`, `ruff`.
- Site: Astro (static output), Pagefind for search, Observable Plot for charts. No client-side analytics, no cookies.
- Node 22 LTS for the site build. *(Changed from Node 20 on 2026-10-11: Node 20 reached end of life in April 2026. Astro pinned to 5.18.x.)*

---

## 4. Sources (verified 2026-10-11)

| City | Platform | Adapter | Status |
|---|---|---|---|
| Helsinki | paatokset.hel.fi (Drupal front of the Ahjo system; old OpenAhjo API closed 12/2024) | `helsinki` | enabled |
| Espoo | Dynasty, `espoo.oncloudos.com` | `dynasty` | enabled |
| Tampere | CaseM / CloudNC, `tampere.cloudnc.fi` | `casem` | enabled |
| Vantaa | Tweb (Triplan), `paatokset.vantaa.fi` | `tweb` | enabled |
| Oulu | Tweb, `asiakirjat.ouka.fi` | `tweb` | **disabled** (robots) |
| Turku | new portal `paatokset.turku.fi` (old archive `ah.turku.fi`) | `turku` | **disabled** (robots) |

Video (link only, v1): Helsinki-kanava (meeting pages embed an `events.icareus.com` player with an `eventId`), Espoo YouTube channel, Vantaa `vantaa.fi/live`, Tampere-kanava, Oulu `ouka.fi/live`, Turku `kepit.tv`.

Per-adapter details are in §7.

---

## 5. Data model

Pydantic v2 models in `kunta/models.py`. JSON on disk mirrors the models. All text is NFC-normalized UTF-8.

### 5.1 IDs (stable, human-readable, used in URLs)
- `city`: `helsinki | espoo | tampere | vantaa | oulu | turku`
- `body_id`: `{city}/{body_slug}` — `body_slug` = ASCII slug of the Finnish name (`ä→a`, `ö→o`, `å→a`), e.g. `helsinki/kaupunkiymparistolautakunta`. Renamed bodies get a new slug; link old→new via `Body.successor`.
- `meeting_id`: `{body_id}/{YYYY-MM-DD}` plus `-2`, `-3` if the body met twice that day.
- `item_id`: `{meeting_id}/{ordinal}` — `ordinal` = 1-based position on the agenda. Do **not** key on § numbers (not assigned at agenda stage; extra "lisäpykälä" items get appended) or on source document IDs (Vantaa issues different document IDs for agenda vs minutes).
- `person_id`: `{city}/{surname-firstname}` with a numeric suffix on collision. Never derived from fuzzy matches (§8).

### 5.2 Models (fields marked `?` are optional)

```text
City         id, name_fi, name_sv?, enabled, adapter
Body         id, city, name_fi, kind, source_ids{...}, active_from?, active_to?, successor?, included: bool
Term         city, start, end                     # 2021-08-01..2025-05-31, 2025-06-01..2029-05-31 (verify per city)
Person       id, city, name (Etunimi Sukunimi), sort_name (Sukunimi Etunimi), aliases[], wikidata?
Membership   person_id, body_id, role(member|deputy|chair|vice_chair|youth_rep|official), group?, party?, start?, end?, source
Meeting      id, body_id, date, start_time?, end_time?, location?, stage(agenda|decisions|minutes),
             source_url, source_ids{...}, minutes_pdf_url?, video_url?, attendance[], items[] (item ids)
Attendance   person_ref, role_text, present: bool, note?          # "saapui klo…/poistui klo…" kept in note
AgendaItem   id, meeting_id, ordinal, pykala?, title, case_number?, presenter?, preparers[]?,
             sections[], motions[], votes[], statements[], disqualified[], attachments[],
             decision_summary?, source_url, source_ids{...}, content_sha256, status(active|tombstone)
Section      type(proposal|deliberation|decision|background|history|statement|dissent|other), heading?, text
Motion       kind(counter_proposal|send_back|table|resolution|other), proposer_ref, seconder_refs[], text, outcome?(adopted|rejected|withdrawn|unknown)
VoteEvent    ordinal, jaa_label, ei_label, counts{jaa,ei,tyhja,poissa}, ballots[], result_text?, source(html|pdf), source_url, needs_review: bool
Ballot       person_ref, choice(jaa|ei|tyhja|poissa), group_text?          # group_text = as printed (Helsinki)
Speech       id, meeting_id, item_id?, ordinal, speaker_ref, speaker_title, kind(speech|reply), lang(fi|sv|mixed), text, video_offset_s?, source_url
Attachment   title, url, kind(attachment|supplementary)
PersonRef    raw (as printed), person_id? (null until resolved), confidence?
```

`content_sha256` = SHA-256 of the item's normalized stored text; used for change detection and the site's "updated" badge.

### 5.3 File layout
- One meeting file per meeting with its items, motions, votes, attendance embedded: `data/{city}/meetings/{yyyy}/{body_slug}--{date}.json`.
- Speeches separate per meeting (large): `data/{city}/speeches/{body_slug}--{date}.json`.
- People per city: `data/{city}/people.json` (persons + memberships).

---

## 6. Adapter interface

```python
class Adapter(Protocol):
    city: str

    def discover_bodies(self) -> list[Body]: ...
    def list_meetings(self, body: Body, since: date, until: date | None) -> list[MeetingRef]: ...
    def fetch_meeting(self, ref: MeetingRef) -> Meeting: ...  # incl. item refs, attendance, stage
    def fetch_item(self, ref: ItemRef) -> AgendaItem: ...  # full text, sections, motions, votes (inline)
    def fetch_votes(
        self, item: AgendaItem
    ) -> list[VoteEvent]: ...  # extra fetches (e.g. vote PDFs); may return []
    def fetch_speeches(self, meeting: Meeting) -> list[Speech]: ...  # may return []
```

Rules:
- Adapters only parse. Rate limiting, robots, caching and retries live in `kunta/http.py`.
- Always fill `source_url`. Every page on the site links back to it.
- Only treat a meeting's votes and attendance as final when `stage == minutes`. Agenda-stage items get proposal text only.
- Sections that describe *earlier* handling (päätöshistoria, aikaisempi käsittely) are stored as `history` sections and are not parsed for votes, except when an adapter explicitly scopes a vote block to the current body (Helsinki item pages contain committee votes from earlier stages — assign those to the earlier body's item only if that item is in our DB; otherwise ignore them).

---

## 7. Adapter specs

### 7.1 Helsinki — `adapters/helsinki.py`

**Bodies.** Seed from:
- `https://paatokset.hel.fi/fi/paattajat/kaupunginvaltuusto`
- `https://paatokset.hel.fi/fi/paattajat/kaupunginhallitus`
- `https://paatokset.hel.fi/fi/paattajat/kaupunginhallituksen-konsernijaosto`
- `https://paatokset.hel.fi/fi/paattajat/kaupunginhallituksen-elinkeinojaosto`
- every link on `https://paatokset.hel.fi/fi/paattajat/lautakunnat-ja-johtokunnat` (committees, sections, enterprise boards; slugs like `kaupunkiymparistolautakunta`, `kasvatus-ja-koulutuslautakunta`, `sosiaali-terveys-ja-pelastuslautakunta`, `kulttuuri-ja-vapaa-aikalautakunta`, `tarkastuslautakunta`, …). The exclude rules in §1 drop `…yksiloasioiden-jaosto`, `…ymparisto-ja-lupajaosto` and `keskusvaalilautakunta`.

**Meetings.** `https://paatokset.hel.fi/fi/paattajat/{slug}/asiakirjat` lists documents, newest first, 25 per page, paginated with `?page=N` (0-based); see S1. Meeting page: `/fi/paattajat/{slug}/asiakirjat/{meeting_code}` (example `02900202614` = council 14/2026; treat the code as opaque). The meeting page shows type ("Esityslista" / "Pöytäkirja"), time, place, item list, minutes print PDF (`ahjojulkaisu.hel.fi/{GUID}.pdf`) and, for the council, the transcript PDF link.

**Items.** Each agenda row links to `/fi/asia/{case-slug}?paatos={decision-guid}` (e.g. `hel-2026-008342`). Row text is `"{ordinal}. / {pykala} § {title}"`. The item page contains, in order: title, case number ("HEL 2026-008342"), the decision for this meeting (Päätös), Käsittely (motions + votes), a structured vote-results section, Päätösehdotus, Esittelijän perustelut, Päätöshistoria (other bodies, with their own Käsittely and votes), Muutoksenhaku (drop), presenter/contact (drop contact), print PDF and attachment PDFs.
- Occasionally the page renders an error placeholder for the decision ("Virhe päätöstä ladattaessa") — treat as transient, retry once later in the run, then record `needs_refetch`.

**Votes (HTML, high quality).** In Käsittely, each vote block is headed "N äänestys" and gives the JAA and EI proposal texts, then `Jaa-äänet: N` followed by a comma-separated list of names (Etunimi Sukunimi), then `Ei-äänet`, `Tyhjä`, `Poissa`. Below, an accordion "Äänestystulokset" repeats each vote as tables with columns *Jäsen* ("Sukunimi, Etunimi") and *Valtuustoryhmä*, plus a per-group summary table. Parse the **tables** for ballots (they include group) and the text blocks for labels and counts; cross-check counts. Votes inside Päätöshistoria belong to earlier bodies (see §6 rule).
- **Vote numbering is not reliable**: on the inspected item the text block was headed "3 äänestys" while the matching table was "Äänestys 1". Pair text blocks with tables by order of appearance and confirm by equal counts; never by the printed number.
- Committee and board votes in Päätöshistoria have only the text form (names, no group column).

**Speeches.** `https://paatokset.hel.fi/fi/paattajat/kaupunginvaltuusto/keskustelupoytakirjat` lists PDFs (`/sites/default/files/{yyyy-mm}/{nn}_kvsto_{ddmmyyyy}.pdf`), paginated with `?page=N`, council only. Parser `speeches_helsinki.py`:
- Every page carries a repeated bilingual header/footer (city name, "keskustelupöytäkirja / diskussionsprotokoll", date, "N / M", postal address block). Strip by detecting lines that recur on ≥ 50 % of pages.
- Skip the table of contents (it ends where the first item heading repeats on a later page).
- Item headings: a line `"{pykala} §"` (sometimes without the space, e.g. `262§`), then `"Esityslistan asia nro {ordinal}"`, then the title (may wrap).
- Speaker headings: a line of the form `{title} {Etunimi Sukunimi}` optionally followed by `(vastauspuheenvuoro)` or `(replik)`. Titles seen: Valtuutettu, Apulaispormestari, Pormestari, Ledamoten (Swedish speakers), Puheenjohtaja. No timestamps.
- Link to items by `ordinal` + `pykala` within the same meeting date.
- Names in headings can contain typos (a doubled letter was seen) — resolution handles it (§8).

**Video.** Store the Icareus player URL from the meeting page as `meeting.video_url` when present.

### 7.2 Espoo — `adapters/dynasty.py`

Base: `https://espoo.oncloudos.com/cgi/DREQUEST.PHP`.

| What | URL |
|---|---|
| Bodies (name, id, latest meeting) | `?page=meeting_frames` |
| Meetings of a body (all years on one page, grouped by year) | `?page=meetings&id={bodyId}` |
| Meeting (items, participants, publish date) | `?page=meeting&id={meetingId}` |
| Item (full HTML text) | `?page=meetingitem&id={meetingId}-{n}` |
| Full agenda/minutes PDF | `https://espoo.oncloudos.com/kokous/{meetingId}.PDF` |
| Item PDF | `/kokous/{meetingId}-{n}.PDF` |
| Attachment PDF | `/kokous/{meetingId}-{n}-{attachmentId}.PDF` |
| RSS (items / meetings) | `?page=rss/meetingitems&show=30`, `?page=rss/meetings&show=30` (the link printed on the site is malformed; build the URL yourself) |

Known body ids on 2026-10-11 (scrape `meeting_frames`, don't hardcode; use these as test expectations): Valtuusto 1, Kaupunginhallitus 182, Kaupunkisuunnittelulautakunta 162, Tekninen lautakunta 160, Kasvun ja oppimisen lautakunta 46162 (+ nuorisoasiainjaosto 46164), KH elinkeino- ja kilpailukykyjaosto 2243, KH konserni- ja tilajaosto 164724, KH konsernijaosto 616, KH tila- ja asuntojaosto 617, KH työllisyys- ja kotoutumisjaosto 165188, KH työllisyysjaosto 152830, Kulttuuri- ja nuorisolautakunta 164718, Kulttuurilautakunta 161, Liikunta- ja hyvinvointilautakunta 164720, Liikuntalautakunta 46112, Nämnden Svenska rum 890, Tarkastuslautakunta 2029, Ympäristö- ja rakennuslautakunta 46088. Several are pre-June-2025 bodies (last meeting May/June 2025) — still in scope.

Quirks:
- Encoding differs by page: listing pages are ISO-8859-1, item pages UTF-8. Decode from the response charset, never assume.
- `meetingId` encodes the year (`20261715` → 2026), but older ids are shorter (`2023987`). Treat as opaque strings.
- Meeting stage: take it from the label on the body's meetings list ("Esityslista" vs "Pöytäkirja"); the meeting page heading can lag. Re-fetch when the label flips.
- Item text is one HTML block with headings: Päätösehdotus, Käsittely, Päätös, Selostus, Päätöshistoria (earlier bodies with their own Käsittely), Liitteet, Oheismateriaali, Tiedoksi. Contact lines ("etunimi.sukunimi@espoo.fi", phone) are dropped.
- Participants table on the meeting page ("Osallistuja" / "Tehtävä") → attendance, **only** at minutes stage. Arrivals/departures appear as notes in the PDF ("saapui klo … § … käsittelyn aikana"); v1 keeps the HTML table only.

**Votes (PDF).** Käsittely text states the counts in prose and says the vote list is attached. The attachment titled `Äänestyslista § {pykala}` is a PDF "Cloudmeeting Äänestystulosraportti" with:
- header: body, meeting, `§ {pykala} {title}`, then a line with the proposal labels (e.g. `{Proposer} Jaa / vastaan Ei / Tyhjä`);
- `Annettuja ääniä yhteensä N`, then `Äänet vaihtoehdoittain` with one line per choice (`Ei 41`, `Jaa 30`, `Tyhjä 4`);
- `Äänet äänestäjittäin`, then one line per member: `{Sukunimi} {Etunimi(s)} {Jaa|Ei|Tyhjä}` — e.g. `Virtanen Matti Ei`, `af Testsson Anna Jaa`, `Mäkinen Juha J. Tyhjä`. Parse by taking the **last token** as the choice; everything before it is the name. No party/group column.
- Some Dynasty installations put several votes in one PDF with `Äänestys:` blocks and choice labels like `Jaa / pohjaehdotus` and `Ei / 6.2`, plus `(Ei äänestänyt)` entries. Support both layouts; map "Ei äänestänyt" to `poissa`.
- Validate: number of ballot lines per choice == the totals in the PDF == the counts in Käsittely prose. Mismatch → `needs_review`.

**Speeches.** None published (video on YouTube only).

### 7.3 Tampere — `adapters/casem.py`

Base: `https://tampere.cloudnc.fi/fi-FI`.

| What | URL |
|---|---|
| Bodies | `/Toimielimet` (names prefixed `Z/` are discontinued bodies — keep them if they met in 2025) |
| Body page (upcoming agenda + minutes grouped by year) | `/Toimielimet/{BodySlug}` e.g. `/Toimielimet/Kaupunginvaltuusto` |
| Meeting | link from body page, e.g. `/Toimielimet/Kaupunginvaltuusto/Kokous_1492026` |
| Item | `/fi-FI/content/{itemId}/{meetingId}` (redirects to a long slug URL; keep the short form as source id) |
| Minutes PDF | `/download/noname/{GUID}/{numericId}` ("Lataa" link on meeting page) |
| Attachments | same `download/noname/...` pattern, listed under "Liitteet" |

Quirks:
- **Do not build meeting URLs from dates**: `Kokous_1492026` (14.9.2026) is ambiguous without separators. Always follow links and parse the date from link text ("Kokous 14.9.2026 Pöytäkirja").
- Body slugs encode Finnish letters oddly (`Asunto_ja_kiinteistoumllautakunta`); take them from links.
- Meeting page lists items `§ {pykala} {title}` and attendance in three groups: present members (with role suffix such as "Puheenjohtaja", "Varajäsen"), other attendees (officials, youth reps), absent. Map to `Attendance`.
- Item page sections: Aikaisempi käsittely (anchors to earlier bodies), Valmistelija, Perustelut, Päätösehdotus oli / Esittelijä, Päätös, Tiedoksi, Liitteet, Muutoksenhaku (drop). Earlier-body blocks repeat on the same page — classify as `history`.
- "Kaupunginvaltuuston kyselytunti" is a question-hour body — include with `kind = council`, no votes expected.
- Every page wraps its content in an ASP.NET `<form>`; parse `#contentAreaDiv`, not the whole page.
- The meeting page has no time or place; take them from the body page's agenda line ("Kaupungintalo, Valtuustosali 19.10.2026 klo.17.00"). Pykälä numbers already show at agenda stage; keep them only once the minutes are out.
- Votes are inline on the item page (S2): one `div.votingResults-header` per vote ("Juho Hirvelän muutosehdotus 1:", "Kaupunginhallituksen ehdotus JAA", "Muutosehdotuksen hyväksyminen EI"), then rows "Kyllä 61 kpl 92%" with the names. "Kyllä" is Jaa. Blocks are in voting order, which can differ from the order of the Kokouskäsittely prose; match a block to its motion by proposer, kind and number, and confirm with the prose result ("Muutosehdotus hylättiin äänin 61-5, poissa 2", winner's count first).

**Speeches.** None published. Video on Tampere-kanava, usually within two working days.

### 7.4 Vantaa — `adapters/tweb.py`

Base: `https://paatokset.vantaa.fi`. (Oulu: same adapter, base `https://asiakirjat.ouka.fi`, council `kirjaamo=695`, disabled.)

| What | URL |
|---|---|
| Minutes search form (body dropdown) | `/ktwebscr/pk_tek_tweb.htm` — parse the `<select>` option values to get body ids ("kirjaamo"); the rendered text shows only names |
| Minutes list for a body (since 2014) | `/ktwebbin/dbisa.dll/ktwebscr/pk_kokl_tweb.htm?+kirjaamo={bodyId}` (council = 55038) |
| Agenda list for a body | `/ktwebscr/epj_kokl_tweb.htm?+kirjaamo={bodyId}` |
| Meeting (minutes) | `/ktwebscr/pk_asil_tweb.htm?bid={bid}` |
| Item document | `/ktwebscr/fileshow?doctype=3&docid={docid}` — **returns a PDF** for most items (check `Content-Type`; some items also have an HTML version) |
| Item attachments | `/ktwebscr/pk_attn_tweb.htm?id={docid}` |
| Compiled minutes PDF ("Kooste") | first row of the meeting page, also a `fileshow` link |
| RSS per body | `/ktwebscr/pk_rssfeed.htm?toimielin={bodyId}` |

Quirks:
- Pages carry `<meta name="robots" content="noindex, nofollow">`. That is about search indexing, not fetching, but keep traffic minimal and still honour robots.txt.
- The dropdown mixes old and new bodies (2025 reorganization, e.g. Kaupunkiympäristölautakunta, Kaupunkikulttuurin ja hyvinvoinnin lautakunta, Kaupunkitilalautakunta alongside older names). Include all decision-making ones that met in 2025. Skip "Stadsfullmäktige" (Swedish duplicate of council documents) and the many "aluetoimikunta / kehittämistoimikunta / seurantaryhmä" bodies.
- The meeting table has rows without § (cover page "Pöytäkirjan kansilehti", appeal instructions) — skip them; ordinal = row order among rows that have a §.
- The item PDF contains the whole case: background, each earlier body's proposal and decision ("Kaupunginhallitus 24.8.2026 § 9 … Päätös: …"), statements entered in the minutes, attachment titles, contact lines. Split by the `{Body} {d.m.yyyy} § {n}` headers; the last block is the current meeting.
- **UNVERIFIED: vote format.** The inspected item had no vote. Spike: find a voted council item and check whether the per-member list is inline in the PDF or a separate attachment.

**Speeches.** Vantaa publishes council transcripts ("Kokouspuheenvuorojen litteraatti") as PDFs under `https://www.vantaa.fi/sites/default/files/document/…` (file names vary, e.g. `Kaupunginvaltuuston kokous 24.2.2025.pdf`). **UNVERIFIED: index page** — spike to find where they are linked (past-meeting pages under `vantaa.fi/fi/kokouskalenteri-menneet` are the first place to look). Format: bilingual cover, then a table of contents where each item heading is followed by lines `H:MM:SS.s {title} {name} ..... {page}`; body repeats item headings and speaker headings. Store the timestamp as `video_offset_s`. Note name order varies (`puheenjohtaja Lindtman Antti` vs `valtuutettu Siri Ahokas`).

### 7.5 Oulu — disabled
Config only. Council agendas `/ktwebscr/epj_kokl_tweb.htm?+kirjaamo=695`, minutes `/ktwebscr/pk_kokl_tweb.htm?+kirjaamo=695` on `asiakirjat.ouka.fi`. Do not fetch until `config/cities.yaml` is flipped by a human after written permission.

### 7.6 Turku — disabled
Stub adapter raising `NotEnabled`. When permission arrives: council documents at `paatokset.turku.fi/kaupunginvaltuusto`; Turku replaced its case-management system around 2025, so early-2025 minutes may sit in the old archive `ah.turku.fi`. Council initiatives are published as structured pages on `www.turku.fi` (initiator + supporters with party) — a good roster source even while the portal is disabled, **if** www.turku.fi robots allow it (check).

---

## 8. People, groups and parties

Goal: every `PersonRef` in ballots, motions, attendance and speeches resolves to a `Person` with time-bounded `Membership`s.

**Roster sources (in priority order):**
1. Helsinki vote tables — name + valtuustoryhmä per vote (authoritative for Helsinki council group at that date).
2. Attendance lists on minutes (Espoo, Tampere, Helsinki body pages) — name + role per body per meeting. These create `Membership(role=member|deputy|chair…)` with `start` = first seen, `end` = last seen.
3. City council member pages (party per councillor), e.g. Vantaa's council page lists every member and deputy with party abbreviation. Write one small scraper per city in `kunta/people_sources/`, run monthly. **UNVERIFIED** for Espoo, Tampere, Oulu, Turku — find the page during M5.
4. 2025 municipal election results (Ministry of Justice results service / Statistics Finland StatFin): candidate name, municipality, party, elected flag. Used to give a party to committee members who were candidates. Only accept a unique name match within the same municipality.
5. Manual overrides: `config/people_overrides/{city}.yaml` (aliases, merges, party corrections).

**Name forms seen:** "Etunimi Sukunimi" (Helsinki prose, transcripts), "Sukunimi, Etunimi" (Helsinki tables), "Sukunimi Etunimi" (Espoo lists, Tampere attendance, Vantaa), particles ("af …"), hyphenated surnames, middle initials ("J."), Swedish letters, occasional typos.

**Algorithm (`people.py`):**
1. Normalize: NFC, collapse whitespace, strip titles (valtuutettu, ledamoten, apulaispormestari, pormestari, puheenjohtaja, varapuheenjohtaja, jäsen, varajäsen), strip trailing role/notes in parentheses.
2. Build candidates = persons with a membership in the same city overlapping the meeting date (any body, so deputies sitting in are found).
3. Match on a canonical key = sorted lowercase tokens without punctuation. Exact key match → resolve.
4. Else `rapidfuzz.token_set_ratio ≥ 92` against candidates **and** unique best → resolve with `confidence`.
5. Else leave `person_id = null` and append to `data/review/unresolved_names.csv` (city, raw, context URL). Never auto-create a Person from steps 3–4.
6. New persons are created only from roster sources 1–3 or overrides.

**Acceptance:** ≥ 98 % of ballots and ≥ 95 % of attendance rows resolved for each enabled city; zero persons merged by fuzzy matching without an override.

---

## 9. Text normalization (`text.py`)

- HTML → text: keep paragraphs and list items, convert simple tables to Markdown tables, drop navigation, share buttons, cookie banners and the "Muutoksenhaku" block.
- Classify sections by heading text (case-insensitive prefix match), mapping per §0. Unknown headings → `other`.
- PII stripping: remove e-mail addresses, Finnish phone numbers (`+358…`, `0\d{1,3}[ -]?\d{3,}…`), and "puhelin …" fragments. Keep the names of officials and members.
- PDF → text (`pdf.py`): pdfplumber per page; drop repeated header/footer lines (appear on ≥ 50 % of pages); re-join hyphenated line breaks only when the next line starts lowercase; keep paragraph breaks on blank lines.

---

## 10. Validation (`validate.py`)

Runs after every crawl; the workflow fails the city (not the whole run) on errors.
- Schema-valid JSON for every file.
- Every item has a `source_url` and non-empty `title`.
- For each `VoteEvent`: `len(ballots by choice) == counts[choice]` for every choice; otherwise `needs_review = true` (warning, not error).
- Meetings at `stage = minutes` have attendance unless the adapter declares none.
- Per city, per run: if the number of meetings found for an active body drops to zero, or parse errors exceed 5 % of fetched items, raise a **layout-change alarm** (error).
- No raw e-mail address or phone number pattern in any stored text (error).

---

## 11. CLI

```
kunta discover   --city C                  # update config/bodies/C.yaml with discovered bodies (keeps manual flags)
kunta crawl      --city C [--body B] --since 2025-01-01 [--until …] [--window-weeks 10] [--revalidate]
kunta speeches   --city C --since …
kunta people     --city C                  # refresh roster sources + resolve refs
kunta validate   [--city C]
kunta export                               # build/exports/*.parquet, *.csv, all.zip
kunta stats                                # counts per city/body, unresolved names, needs_review
```
All commands are idempotent and resumable (state in `data/state/{city}.json`: per body, last seen meeting, per URL ETag/Last-Modified/sha256).

---

## 12. Scheduling and workflows

Meetings are mostly on Mondays (Helsinki council on Wednesdays); minutes appear about a week later; Helsinki transcripts about two weeks later; personal data is removed from source minutes after the appeal period.

| Workflow | Trigger | Does |
|---|---|---|
| `weekly.yml` | `cron: '23 3 * * 6'` (Sat 03:23 UTC) + `workflow_dispatch` | per enabled city in a matrix: crawl meetings dated in the last **10 weeks** + new meetings, speeches, people resolve, validate; then one job commits `data/`, writes heartbeat, builds site, deploys Pages |
| `monthly.yml` | `cron: '41 2 2 * *'` (2nd of month) | `crawl --revalidate --since 2025-01-01` with conditional GETs; catches removals/edits; then same tail |
| `backfill.yml` | `workflow_dispatch(city, body?, year?)` | slice crawl for initial load; commits per slice |
| `smoke.yml` | `cron: '7 6 * * 3'` | one live fetch + parse per adapter against a known page; opens a GitHub issue if it fails |

Details:
- Don't combine day-of-month and day-of-week in one cron line (cron ORs them).
- `concurrency: group: data-writer, cancel-in-progress: false` on every workflow that commits.
- Permissions: `contents: write`, `pages: write`, `id-token: write`, `issues: write`.
- Cache `.cache/raw` with `actions/cache` keyed by city + ISO week, restore-keys by city.
- Crawl jobs run in parallel per city (different hosts); within a city stay sequential.
- Job timeout 330 min. Backfill sizing: assume ~15–25k item fetches for all enabled cities since 2025 at 1 req/s per host → run backfill per city, per year, possibly per body.
- On failure: `gh issue create` with city, step, last 50 log lines; dedupe by title.
- Deploy with `actions/upload-pages-artifact` + `actions/deploy-pages`.

---

## 13. Site (Astro, `site/`)

Finnish UI at the root, Swedish under `/sv/`, English under `/en/` (since 2026-10-12). Item pages are built once, at the Finnish path, and translated client-side with `?lang=` so the three locales don't triple the largest part of the site.

**Routes**
```
/                                          cities, latest decisions, upcoming meetings
/{city}/                                   bodies, recent meetings, recent votes
/{city}/{body}/                            meetings by year, members (current term)
/{city}/{body}/{date}/                     meeting: attendance, items, video link, source links
/{city}/{body}/{date}/{ordinal}/           item: decision, full text sections (history collapsed), motions, votes, speeches, attachments, case timeline
/{city}/asia/{case-number-slug}/           case timeline across bodies (items sharing case_number)
/{city}/henkilot/{person}/                 memberships, attendance %, voting record, motions; speech COUNT only (§2.2 rule 9)
/{city}/ryhmat/{group}/                    group cohesion, splits
/haku/                                     Pagefind search (filters: city, body, year, kind)
/data/                                     downloads + schema docs + licence
/tietoa/                                   about, method, sources, privacy notice, takedown contact
```

**Features v1**
- Vote view: Jaa/Ei/Tyhjä/Poissa bars, per-group breakdown, member list; highlight members voting against their group's majority.
- Person page: votes table with filters, "voted against group majority" count, attendance rate per body.
- Every page shows "Source: {city system}" link and "last updated" date.
- Search index: titles + decisions + proposals; exclude `history` sections and speeches from the default index to keep it small (speeches get a separate optional index if size allows).
- Accessibility WCAG 2.1 AA; works without JS except search and charts.
- No analytics, no cookies, no third-party embeds until clicked (video links open the source site).

**Size budget.** Measure after M1: bytes of HTML per item × projected items. If the projection exceeds 700 MB, stop rendering `history` sections in full (link to the source instead) and move exports to a GitHub Release asset.

---

## 14. Testing

- `tests/fixtures/{city}/`: a few saved pages per adapter (list, meeting, item with vote, item without vote, vote PDF, transcript PDF first 3 pages). Keep each under 1 MB.
- Unit tests per parser with golden JSON outputs (`tests/golden/`). Update goldens only deliberately (`pytest --update-goldens`).
- Tests for: robots refusal, rate limiter timing, PII stripping, name normalization and resolution, ID stability (re-parse same fixture twice → same IDs), deterministic serialization.
- Fixture expectations to encode now:
  - Helsinki council item `hel-2026-008342` (council 23.9.2026, § 261): exactly one council `VoteEvent` (34 Jaa / 36 Ei / 15 Tyhjä / 0 Poissa) with group per ballot; the city board's three votes and the committee's three votes in Päätöshistoria are not attached to the council item.
  - Espoo vote PDF: 75 ballots, counts Ei 41 / Jaa 30 / Tyhjä 4 match totals (use the real PDF from council 21.9.2026 § 132 as fixture).
  - Helsinki transcript: item headings for § 256, 258–262 found; replies flagged.
- CI (`ci.yml` on push/PR): ruff, pytest, `kunta validate` on committed data, site build.

---

## 15. Milestones

Each milestone: open a PR, include `kunta stats` output in the description.

### M0 — Skeleton
- Repo layout §3.1, `pyproject.toml`, ruff, pytest, CI workflow, `AGENTS.md` pointer.
- `kunta/http.py` with robots, per-host rate limit, retries, conditional GET, raw cache.
- Models §5, ID helpers, deterministic JSON writer.
- **Accept:** CI green; tests for robots refusal, rate limit, determinism pass; `config/cities.yaml` has Oulu/Turku disabled with reasons.

### M1 — Helsinki vertical slice
- `discover_bodies`, `list_meetings` (spike pagination first), `fetch_meeting`, `fetch_item`, HTML votes parser.
- Minimal site: city → body → meeting → item pages, source links.
- `weekly.yml` running for Helsinki only (no deploy of other cities).
- **Accept:** all in-scope Helsinki bodies discovered; every minutes-stage meeting since 2025-01-01 present; ≥ 99 % of items have a decision section; every council vote's ballot counts equal printed counts (or `needs_review` with a reason); a second run produces no diff; site deploys to Pages; size measurement recorded in §13.

### M2 — Espoo
- Dynasty adapter, encoding handling, stage detection, Cloudmeeting vote PDF parser (both layouts).
- **Accept:** body ids match §7.2 expectations; all 2025+ meetings present; for every item whose Käsittely mentions a vote list, a `VoteEvent` exists with matching counts; fixture tests pass.

### M3 — Tampere
- Vote-format spike first (write result into §16), then CaseM adapter + vote parser.
- **Accept:** as M2; attendance parsed for all minutes-stage meetings.

### M4 — Vantaa
- Vote-format spike; body-id extraction from the form; item PDF splitter (current block vs earlier bodies); RSS used for incremental discovery.
- **Accept:** as M2; no § -less rows imported as items.

### M5 — People and groups
- Roster sources §8 (spike council member pages for Espoo/Tampere), election-data seeding, resolver, overrides, review CSV.
- Group cohesion + "against group majority" metrics in the export step.
- **Accept:** thresholds in §8 met for Helsinki, Espoo, Tampere, Vantaa.

### M6 — Speeches
- Helsinki transcript parser; Vantaa transcript index spike + parser with timestamps.
- **Accept:** ≥ 95 % of speeches in 2025+ Helsinki transcripts linked to an item and a resolved person; Vantaa speeches carry `video_offset_s`.

### M7 — Site v1
- All routes §13, search, charts, downloads page, about/privacy/takedown page, i18n scaffolding.
- **Accept:** Lighthouse accessibility ≥ 95 on item and person pages; published site < 700 MB; Pagefind index < 100 MB.

### M8 — Operations
- `monthly.yml`, `backfill.yml`, `smoke.yml`, heartbeat, failure issues, layout-change alarms, takedown application.
- **Accept:** a simulated layout change (fixture swap) opens an issue; a takedown entry removes text from the built site; heartbeat commits even when no data changed.

### M9 — Oulu and Turku (blocked)
- Starts only after a human sets `enabled: true` with a link to the written permission in `config/cities.yaml`.

---

## 16. Unverified assumptions and spike log

Fill in "Result" as you resolve each one.

| # | Question | Where | Result |
|---|---|---|---|
| S1 | Helsinki `/asiakirjat` pagination / year filter | §7.1 | 2026-10-11: `?page=N` (0-based), 25 rows per page, newest first; each row is a link `Esityslista N - YYYY` / `Pöytäkirja N - YYYY` to `/asiakirjat/{code}` (agenda rows carry `#paatostiedote`) plus a `Päätöksentekopäivä: d.m.yyyy` line. A year filter exists but its parameter was not visible; not needed — the adapter pages until it passes `since`. Note the listing label can lag the meeting page (council 14/2026 listed as Esityslista while its page was already Pöytäkirja), so stage comes from the meeting page's h1. |
| S2 | Tampere vote format (inline vs attachment) | §7.3 | 2026-10-13, recorded pages (council 10.11.2025 § 176, budget, 19 votes): inline on the item page, under "Äänestystulokset", one header per vote naming the motion and which side was Jaa/Ei, then "Kyllä/Ei/Tyhjä/Poissa N kpl" rows with comma-separated names. No vote attachment. The Kokouskäsittely prose lists motions ("X oli tehnyt seuraavan muutosehdotuksen", numbered "Muutosehdotus N:", "Y kannatti X:n muutosehdotusta", renewed board-stage motions "jotka Z uudisti") and results ("äänin 61-5"). Confidential items are titled "… (Salassa pidettävä)". Fixtures are recorded pages with contact details replaced (`tests/fixtures/tampere/`). |
| S3 | Vantaa vote format | §7.4 | |
| S4 | Vantaa transcript index page | §7.4 | |
| S5 | Council member pages with party: Espoo, Tampere | §8 | |
| S6 | Does Helsinki's päätöstiedote stage carry votes? (if yes, votes can appear a week earlier) | §7.1 | 2026-10-11, council 15/2026: no. Entries read "Ehdotuksen mukaan." plus elected names; no counts or ballots. Meetings with a filled päätöstiedote are stored as `stage = decisions`, without votes. |
| S7 | Exact council term start dates per city (assumed 2025-06-01) | §5.2 Term | |
| S8 | Election results download path (Ministry of Justice / StatFin) | §8 | |
| S9 | www.turku.fi robots allows initiative pages | §7.6 | |
| S10 | Espoo page and vote-PDF structure | §7.2 | 2026-10-13, by hand: the §7.2 tables and link shapes hold. `meeting_frames` lists bodies without meetings ("Testitoimielin") as plain text. The meeting page's h1 carries body, stage, date, `klo 17.30 - 19.53` (dot or colon), "⁄ Tarkastettu" and the place; the participants table (Osallistuja / Tehtävä) is present at agenda stage too, so attendance is kept only at minutes stage. Item text opens with `Asianumero …`, `{Body} dd.mm.yyyy § n`, `§ n`, the title and a "Valmistelijat / lisätiedot" table; "Päätösehdotus Esittelijä" is followed by the presenter on its own line, and Päätöshistoria blocks are headed `{Body} dd.mm.yyyy § n` with plain "Käsittely"/"Päätös" lines inside. Votes: Käsittely says "Äänestyksessä valtuusto 30 äänellä 41 ääntä vastaan, 4 äänestäessä tyhjää hylkäsi … Äänestyslista on pöytäkirjan liitteenä."; the first number is the Jaa side. Smaller bodies write numbers as words ("yhden äänestäessä tyhjää"). One vote → attachment "Äänestyslista § n" (layout 1, legend `{Proposer} Jaa / vastaan Ei / Tyhjä`); several → one "Äänestyslistat § n" PDF with `N. Äänestys: Jaa: {label} / Ei: vastaan / Tyhjä` blocks (layout 2; council 8.12.2025 § 167 has six). A deputy can be printed over three lines (`Name`, `(Member replaced)`, `Ei`). Option totals are not in a fixed order. No page headers or footers in the vote PDFs. The build environment could not reach the host, so fixtures are reconstructed (`scripts/make_espoo_fixtures.py`). Recorded pages (2026-10-13, `tests/fixtures/espoo/real/`) add: the item text sits in `div.data-part.meetingitem` under "Kokousasian teksti"; attachments and supplementary material are separate `div.data-part` blocks (the "Liitteet" list inside the text has no links); paragraphs are Word-style `<p><span>` runs, so a heading can share a paragraph with its first sentence ("Päätös Puheenjohtaja totesi …"); item pages are UTF-8, listing and meeting pages ISO-8859-1. |

---

### Build log

- 2026-10-13 — M3 Tampere adapter (draft): bodies from the side navigation (`Z/` prefix dropped from the name, youth, elderly, immigrant and substance-abuse councils excluded), meetings from the body page with time and place from the agenda line, meeting page items and three attendance groups (kept at minutes stage), item pages with history per earlier body, presenter, preparers, sections, attachments, motions from the Kokouskäsittely prose and inline votes matched to motions by proposer, kind and number. A vote is `needs_review` when its names do not add up to its counts, or when no prose result matches it. The proxy could not reach the host, so pages were recorded by `record-pages.yml`; `tests/fixtures/tampere/` are those pages, trimmed, with emails and phone numbers replaced. Live crawl and acceptance after merge.
- 2026-10-13 — M2 Espoo adapter (draft): body discovery from `meeting_frames`, all-years meeting listing with stage from the label (the page heading wins only when it already says Pöytäkirja), meeting page (times, place, minutes PDF, items, participants → attendance at minutes stage), item text split by heading lines, history blocks per earlier body, attachments, motions from "X Y:n kannattamana teki/ehdotti/esitti", Cloudmeeting vote PDFs in both layouts paired with the Käsittely prose by order and checked three ways (ballots = PDF totals = prose counts, else `needs_review` with the reason). A vote list that 404s keeps the prose counts with `needs_review`; a 5xx retries later in the run. Listing pages are decoded as UTF-8 when valid, else by the declared charset (Windows-1252 for ISO-8859-1). `weekly.yml` crawls Helsinki and Espoo and takes `cities` and `body` inputs for targeted re-runs. Helsinki loose end: the three council votes flagged "table counts differ" are the city's own inconsistency, each with one member recorded under a different choice in the table than in the minutes text (council 9.9.2026: Ville Merinen, Jaa in the text, Ei in the table). The parser now names the member in `review_reason`, keeps the text's ballots and counts, and takes each member's group from the table, so these votes show groups again.
- 2026-10-12 — Site: Swedish and English UI with a language switcher; all votes as cards per city and year (`/{city}/aanestykset/`); members and party presence on body pages, derived from vote records until M5 (council seats from the latest council vote, members = most-present per group this term); city coats of arms and public-domain/CC0 photos from Wikimedia Commons (`config/images.yaml`, fetched in CI because the build environment cannot reach Wikimedia); city mottos removed. Size with Helsinki data: 219 MB built, up from 183 MB (item pages 102 MB, 14.6 KB each, now with per-member vote dots; sv/en copies of the other pages 17 MB; Pagefind 49 MB). The §13 projection stays under the 700 MB line.
- 2026-10-12 — M1 live: two Helsinki crawls since 2025-01-01. 21 bodies, 532 meetings, 7,013 items, 454 votes (11 `needs_review`, all with a reason). The first run exposed forwarded matters (decision headed Esitys/Lausunto), Swedish section headings and case codes caught as phone numbers; fixed in PR #3. Decision coverage 100 % of public minutes items; the 126 items titled "Salassa pidettävä" (Publicity Act) never get a public decision and are now final, not `needs_refetch`, and are left out of coverage. Size (§13): data/helsinki 72 MB raw JSON (15 MB gzipped); site build 183 MB, of which item pages 90 MB (12.8 KB each) and Pagefind 49 MB, so about 26 KB per item all-in. Projection with §12's 15–25k items for all enabled cities since 2025: 0.4–0.65 GB, under the 700 MB line, so `history` (16 % of section text) stays rendered for now. Helsinki adds about 4k items a year, so re-measure after M2 lands Espoo. Open: three council votes where table and text counts differ.
- 2026-10-11 — M1 Helsinki adapter (draft): body discovery from the committees page and menu, paginated meeting listing, meeting and item pages, HTML vote parser (text blocks paired with the Äänestystulokset tables by order, confirmed by counts; `needs_review` carries a `review_reason`), motions, history sections, crawl loop with a rolling refetch window, transient-error retry, `needs_refetch` state, tombstones after two 404s, layout-change alarm, `weekly.yml` for Helsinki. `kunta/robots.py` replaces `urllib.robotparser`, which ignores the `*` wildcards in paatokset.hel.fi's robots.txt. Parsers key on visible text and URL shapes, not CSS classes. The build environment could not reach paatokset.hel.fi, so `tests/fixtures/helsinki/` are reconstructed from the inspected structure (fictional names, real counts) and must be swapped for recorded pages after the first live run. Meeting pages carry no participant list, so Helsinki attendance waits for M5 (`has_attendance = False`). Size measurement (§13): see 2026-10-12.
- 2026-10-11 — M0 skeleton landed together with a basic site (ahead of M7): city/body/meeting/item routes, `/haku/` (Pagefind), `/data/`, `/tietoa/`, six city themes, Finnish i18n dictionary with room for sv/en. Person, group and case routes wait for M5/M7. A fictional dataset in `site/demo-data/` drives preview builds and CI. Adapters are stubs that raise until their milestone.

---

## 17. Decisions waiting on humans (defaults in force until changed)

| Topic | Default |
|---|---|
| Site name, domain, contact e-mail for User-Agent | Set 2026-10-11 by Savvas: Kotihiiri, `savvyboi.github.io/kotihiiri`, project contact e-mail in `config/project.yaml` |
| Licence for our normalized data | CC BY 4.0, attributing the cities as source |
| Body exclude list (§1) | as written |
| Per-person speech collections | off (`SPEECHES_BY_PERSON=false`) pending legal check |
| Oulu / Turku | disabled pending written permission |
