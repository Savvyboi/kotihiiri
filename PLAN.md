# Finnish city decisions site — implementation plan

> **For the coding agent.** This is the build spec. Work milestone by milestone (§15), in order. Each task has acceptance criteria; a milestone is done only when all of them pass. Anything marked **UNVERIFIED** must be checked with a short discovery spike before you write the parser, and the result written back into this file (§16). Hard constraints in §2 are non-negotiable — if a task seems to require breaking one, stop and ask a human.

Last research pass: 2026-10-11. URLs and page structures below were checked by hand on that date.

**Scope change 2026-10-13:** the site grows from the six largest cities to **96 municipalities** (those six plus ranks 7–96). The registry, hosting move and new milestones are in §18; §1, §2.3, §3 and §15 point there. Until M11 lands, everything below describes the running six-city system.

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

**Expansion (decided 2026-10-13, details §18):** the 90 next-largest municipalities, ranks 7–96 by Statistics Finland's preliminary population of 31 Mar 2025 (Jyväskylä #7 … Sotkamo #96), listed in `config/registry/municipalities_rank7-96.csv`. Same content and body rules as above, with two differences: a municipality is enabled only after its hosts pass the robots audit (§18.2), and new municipalities start with council and municipal board only, adding committees once hosting is on Cloudflare (§17). "City" in field names and URLs keeps meaning *municipality* (kunta); about a third of the 96 are not cities.

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
9. **Speeches by person:** a page that collects all speeches of one person needed a human to confirm the legal check first (Finnish Copyright Act has a specific rule on speeches in public bodies). Savvas confirmed the check on 2026-10-14, so `SPEECHES_BY_PERSON=true` in `config/project.yaml`; person pages list a person's speeches with a short excerpt and link to the full text on the item page. Setting the flag back to `false` removes the list again.
10. Deterministic output: same input → byte-identical JSON (sorted keys, stable list order, no "fetched_at" inside content files; volatile metadata goes to `data/state/`). A no-change run must produce an empty git diff (except the heartbeat file).

### 2.3 Hosting limits (GitHub Pages)
*These hold until M11 moves the site to Cloudflare (§18.4). 96 municipalities do not fit them: the projected site is several GB and the canonical JSON alone passes the 1 GB repo guideline.*
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

From M11 the site and canonical data move to Cloudflare R2 and the crawl stays on GitHub Actions; target architecture in §18.4.

### 3.1 Repository layout

```
.
├── PLAN.md                     # this file
├── AGENTS.md                   # short pointer: "read PLAN.md; constraints in §2"
├── config/
│   ├── project.yaml            # site domain, contact email, user agent
│   ├── cities.yaml             # the six cities: enabled flag, adapter, base URLs, reasons
│   ├── municipalities.yaml     # GENERATED (`kunta registry`): all 96, from cities.yaml + registry/ + robots audit
│   ├── registry/               # ranks 7–96 CSV, rollout.yaml (which audited ones are on), audit-args
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

Per-adapter details are in §7. Ranks 7–96 are in `config/registry/municipalities_rank7-96.csv` and summarized in §18.1.

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
- Board agenda titles end with the presenter's initials ("… / PT", "…/PT (kvalt)", "… / TeA"); strip them.
- Agenda-stage meetings are on the agenda list only until the minutes are out (`epj_asil_tweb.htm?bid=`); the minutes list then carries the meeting. Both lists are one request per body, so the RSS feeds are not needed for incremental discovery.
- Item PDFs open with the title (it can wrap), the diary number (`VD/7118/02.03.00.00/2025`) and the preparers' initials. Each block has "… esitys:", "Käsittely:" and "Päätös:"; "_____" lines separate episodes inside a Käsittely. "Liite:" / "Liitteet:" lists attachment titles without links (the links are on `pk_attn_tweb.htm?id=`); everything after "Muutoksenhakuohje" / "Lisätiedot:" is appeal text and contact lines (phone numbers, e-mail) and is dropped. A document fetched later can already carry later handling, so the meeting's own block is the one with its date and §.
- **Attendance:** the cover page PDF ("Pöytäkirjan kansilehti", a §-less row) has "Aika d.m.yyyy klo hh.mm–hh.mm", "Paikka …" and the participants in two columns: "Surname First[, role] x|-" with an optional "(klo … § …)" note that can wrap or be cut by the next column. Groups: Jäsenet, Varajäsenet (First Surname on council covers; an unmarked list on board covers means not called), Kaupunginhallituksen jäsenet, Nuorisovaltuuston edustaja, Muut osallistujat. Meetings before 2026 have no cover row; the compiled minutes ("Kooste", up to 26 MB for a budget session) open with a table of contents and then the same cover page, so the adapter reads only its first pages. Layouts vary by body: the mark is `x` or `X`; committees may head the columns "Jäsenet Varajäsenet" with no "Läsnä" and leave absent members unmarked, so an unmarked name can run into the next column's entry; the time can follow a comma ("Aika 8.6.2026, klo 13.05–17.26"); Swedish bodies write "Protokollets försättsblad", "Tid [weekday] dd.mm.yyyy[, kl.] hh.mm-hh.mm", "Plats", "Medlemmar Närvarande Personliga ersättare Närvarande", "Övriga deltagare". The second column of a "Jäsenet … Varajäsenet" table holds deputies. Some 2025 meetings of the smaller bodies publish neither a cover row nor a compiled PDF; they have no attendance.
- **Votes (verified 2026-10-13, §16 S3):** the Käsittely prose names the motion ("valtuutettu Antero Eerola esitti valtuutettu Gashaw Bibani kannattamana, että …"; an unseconded one "raukesi kannattamattomana"), the voting proposal ("he, jotka kannattavat kaupunginhallituksen pohjaesitystä, äänestävät jaa, ja he, jotka kannattavat valtuutettu Eerolan … muutosesitystä, äänestävät ei") and the counts ("Äänestyksessä annettiin 61 jaa-ääntä ja 6 ei-ääntä", "… 12 ei-ääntä ja yksi tyhjä-ääni"). Boards add the voters' surnames in brackets ("13 jaa-ääntä (Karinen, Tammi, …) ja 2 ei-ääntä (Roininen, Niikko)"). The per-member list is an attachment "Äänestysraportti kv 17.11.2025 § 10", one block per vote: "Vote name: JAA=Pohja EI=Eerolan muutosesitys", "Agenda name: § 10 …", "Vote start: 17/11/2025 22.44.09" (or `4.11.2025 …`), totals, group totals, then "Individual Voting Results" with "First Last party" lines under JAA / EI / Tyhjää (absentees are not listed). A council item also carries the board's earlier reports ("Äänestysraportti KH 4.11.2025 § 6 Kasonen"), so reports are kept only for this § and date (a vote after midnight is dated the next day). Reports pair with the prose by counts, then order; the prose and the report can disagree (council 17.11.2025 § 9: 53–12–1 in the text, 54–12–1 in the report), which is flagged with both sides.

**Speeches.** Vantaa publishes council transcripts ("Kokouspuheenvuorojen litteraatti") as PDFs under `https://www.vantaa.fi/sites/default/files/document/…` (file names vary, e.g. `Kaupunginvaltuuston kokous 24.2.2025.pdf`). **UNVERIFIED: index page** — spike to find where they are linked (past-meeting pages under `vantaa.fi/fi/kokouskalenteri-menneet` are the first place to look). Format: bilingual cover, then a table of contents where each item heading is followed by lines `H:MM:SS.s {title} {name} ..... {page}`; body repeats item headings and speaker headings. Store the timestamp as `video_offset_s`. Note name order varies (`puheenjohtaja Lindtman Antti` vs `valtuutettu Siri Ahokas`).

### 7.5 Oulu — disabled
Config only. Council agendas `/ktwebscr/epj_kokl_tweb.htm?+kirjaamo=695`, minutes `/ktwebscr/pk_kokl_tweb.htm?+kirjaamo=695` on `asiakirjat.ouka.fi`. Do not fetch until `config/cities.yaml` is flipped by a human after written permission.

### 7.6 Turku — disabled
Stub adapter raising `NotEnabled`. When permission arrives: council documents at `paatokset.turku.fi/kaupunginvaltuusto`; Turku replaced its case-management system around 2025, so early-2025 minutes may sit in the old archive `ah.turku.fi`. Council initiatives are published as structured pages on `www.turku.fi` (initiator + supporters with party) — a good roster source even while the portal is disabled, **if** www.turku.fi robots allow it (check).

### 7.7 Votes from the minutes text — `parsers/votes_prose.py`
Most registry municipalities (Dynasty and CloudNC) attach no vote list, or one we cannot read, and write the vote only in the Käsittely or decision text, each in its own words. `votes_prose` reads those sentences: counts with the voters in brackets ("9 JAA-ääntä (…)"), named sides ("pohjaesitys sai 7 ääntä", "palautuksen puolesta 10 jäsentä", "motförslaget fick 6 röster"), table rows ("JAA 7"), bare results ("äänin 35–15", "tulokseksi 9–2", "tasan 5-5", "8 äänellä 5 vastaan"), blanks and absentees, and the voting proposal that says what Jaa and Ei meant. Number words become digits. Named sides must look like a proposal (esitys, ehdotus, palautus, pöydälle …), so a person election is never read as a vote. A restated result is not a second vote. A vote is `needs_review` when its names do not add up to its counts, when a name is on two sides (ballots dropped), or when only a bare result is printed and nothing says which count was Jaa. Dynasty uses it where no vote list gave ballots; CloudNC uses it where the page has no vote table and to confirm table counts. `scripts/votes_audit.py` (and `votes-audit.yml`, which reads R2) prints per municipality how many items mention a vote and how many have one, with sample sentences, so a gap can be read from the workflow log.

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
/{city}/henkilot/{person}/                 memberships, attendance %, voting record, motions; speeches with excerpts (§2.2 rule 9)
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
- Vote-format spike; body-id extraction from the form; item PDF splitter (current block vs earlier bodies); minutes and agenda lists for discovery (RSS not needed, §7.4).
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

### M10 — Registry and robots audit (96 municipalities)
- `config/municipalities.yaml` generated from the registry CSV plus the six cities (§18.1): slug, names (fi/sv), population, platform, adapter, base URLs, council organ id, councillor source, `enabled`, `reason`.
- `robots-audit.yml` (workflow_dispatch, runs on Actions because the build environment can't reach most hosts): fetch robots.txt for every host in the registry, test the paths each adapter needs, write `robots_status` + date per host to `data/state/robots.json`. Hosts that disallow get `enabled: false, reason: robots_disallow_pending_permission`, same as Oulu.
- Count meetings per council and board since 2025-01-01 from listing pages only (no item fetches) to replace the §18.3 estimate.
- **Accept:** every registry row has an adapter or `adapter: none` with a reason; every host has a robots result; §18.3 numbers replaced with counts.
- Built 2026-10-15: `kunta registry` writes `config/municipalities.yaml` (all 96, rank order) from `cities.yaml`, the CSV, `data/state/robots.json` and `config/registry/rollout.yaml`; a registry municipality is `enabled` only with an adapter, every host `allowed`/`no_robots` in the audit, and its slug in the rollout, else `reason` is `no_adapter`, `robots_audit_pending`, `robots_disallow_pending_permission`, `host_unreachable` or `rollout_pending`. CI fails if the generated file is stale. `kunta audit` (run by `robots-audit.yml` on a push of `config/registry/audit-args` or by dispatch) checks each host's robots.txt against the adapter's paths and counts council and board meetings from listing pages; results in `data/state/robots.json` and `data/state/audit.json`. Slugs are the Finnish names (Raasepori, Mustasaari, Pietarsaari, Parainen, Maarianhamina), with `lang: sv` for the Swedish-language ones. Registry municipalities carry `bodies_scope: council_board`. Shared providers get the 2 req/s cap in `kunta/http.py` (one lock per provider).

### M11 — Move hosting to Cloudflare
- §18.4: canonical JSON and state in a private R2 bucket, built site in a public R2 bucket behind Savvas's domain, crawl and build on Actions, `rclone sync --checksum` uploads only changed files. GitHub Pages stays live until the Cloudflare site matches it page for page.
- Site build must be byte-stable (no build time in pages, only data dates) so unchanged pages are not re-uploaded.
- Needs Savvas's steps in §18.6 first.
- **Accept:** the six-city site served from Cloudflare with identical page count; a no-change weekly run writes zero objects to R2; `data/` removed from git with a final snapshot kept as a Release asset.
- Log 2026-10-15: `pages.yml` gained `r2-ready` + `r2` jobs (root build for `https://kotihiiri.eu/`, `rclone sync --checksum` into `kotihiiri-site`); they skip until the §18.6 secrets exist. Two identical local builds (43,839 files) differed only in 3 `pagefind/filter/*.pf_filter` files and `pagefind-entry.json`, so a no-change run currently rewrites ~4 objects; the Astro pages and exports are byte-stable. Still open: the `/` → `index.html` transform rule on the zone (§18.4).

### M12 — Dynasty rollout (47 municipalities)
- **Resume here (2026-10-16, evening).** Audit done (M10 log). `config/registry/rollout.yaml` enables 51 registry municipalities: batch 1 (10 Dynasty on oncloudos.com + the 10 CloudNC, M13) and batch 2 (the other 31 audit-allowed Dynasty ones). All 51 crawled (`window_weeks: all`, weekly runs 38822086912, 38902448823, 38902452542), passed validation and are in R2 `kotihiiri-data`. The batch 1 validation failures were titles with post numbers (virkanumero, vakanssinumero) and property ids, not phone numbers; `strip_pii`/`contains_pii` now keep those, and validation logs the shape of any match. Parainen waits: its council moved from "Kaupunginvaltuusto" to a new "Valtuusto" body in 2025, so it has two council bodies. The scheduled weekly run covers all of them again (un-paused at Savvas's request, 2026-10-16). Councillors with party for all 55: M15 log. Next: (1) Parainen; (2) check the first scheduled run fits the job budget with 31 municipalities on oncloudos.com; (3) check the deployed R2 site build shows the 51 with data; (4) M14 Tweb is blocked on robots.txt for all 26 (permission needed).
- Generalize `dynasty.py` from Espoo: base URL and council organ id from the registry, self-hosted `…/cgi/DREQUEST.PHP` hosts, lenient RSS parsing for incremental discovery. Bring municipalities in in batches of about ten, smallest-risk first (live-verified `oncloudos.com` rows).
- **Accept per batch:** as M2 on council and board; `needs_review` share of votes ≤ 25 % with every flag carrying a reason.

### M13 — CloudNC rollout (10)
- `casem.py` with per-municipality base URL; organ slugs from links only (§7.3).
- **Accept:** as M3 per municipality.

### M14 — Tweb rollout (robots-permitting)
- Needs M4 (Vantaa) first. Only hosts the M10 audit allowed; self-hosted paths under `/ktwebbin/dbisa.dll/` and non-standard ports (Jakobstad `:8443`). Swedish-language minutes for Raseborg, Jakobstad, Pedersöre and Mariehamn (§18.5).
- **Accept:** as M4 per municipality.

### M15 — Councillors for all municipalities
- Seed council rosters with party for every municipality from Statistics Finland's 2025 municipal-election data (PxWeb API, S8), then attendance lists and Tweb `lumu_organ.htm` registries (§8 sources 2–3) for replacements and committees. Mariehamn needs a separate source (Åland elections).
- **Accept:** every enabled municipality's council page lists its councillors with party; §8 resolution thresholds met per municipality.
- Log 2026-10-16 (at Savvas's request, for the 55 enabled municipalities): every municipality gets `statfin_candidates_table` from `config/registry/electoral_districts.yaml` (the twelve 2025 candidate tables, 14uk–14v8, one per electoral district; Maarianhamina has none), so `kunta people` gives party, result and votes everywhere; rosters still come from attendance lists (Tweb `lumu_organ.htm` not needed yet). `people.yml` now covers R2 municipalities: it reads their meetings from R2 and writes `people.json` back to R2 only on main. Name forms the registry minutes print: a party after the name ("Aaltonen Minna, KOK", Nurmijärvi), first name first with a glued initial ("Ari.M Laitinen", CloudNC), a deputy role in the name column ("Henri Ihander (varajäsen", Järvenpää), notes in the name column ("Kokouksessa tauko klo …", Mikkeli), Swedish "viceordförande". The subset match now needs the candidate's surname in the printed name and takes the name order from the list. Trial run on the branch: 2,454 of 2,471 elected councillors (99.3 %) found in the rosters, all 55 validate; 41 municipalities find every elected councillor; 63 people seen on councils this term have no party (name forms the election data prints differently, e.g. three middle names in Vihti, "Elma.S" in Jyväskylä, two Pekka Laitinens in Savonlinna). Overrides (same day): `config/people_overrides/{city}.yaml` maps a printed name to its candidate (`"Name / PARTY"` for namesakes); `kunta people` prints the candidates sharing a name with each councillor left without a party, and the elected candidates no roster person took. 33 overrides (spelling and hyphen forms, namesakes where only one candidacy can sit on the council, Sofia Vikman, and elected candidates missing from the roster with a councillor's first name, marked inferred) bring it to 2,466 of 2,471 elected councillors; 31 people seen on councils this term still have no party, none of them an unmatched elected candidate. A web search found sources for only one of them.

### M16 — Long tail
- Spike each: M-Files Kokoukset (Imatra, Lappeenranta), Korsholm (own WordPress site, FI/SV), Kotka (new system since 3.11.2025), Hyvinkää, Kurikka, Alavus (system not identified). Write an adapter only where two or more municipalities share it or the source is structured; otherwise keep `enabled: false, reason: no_adapter`.

---

## 16. Unverified assumptions and spike log

Fill in "Result" as you resolve each one.

| # | Question | Where | Result |
|---|---|---|---|
| S1 | Helsinki `/asiakirjat` pagination / year filter | §7.1 | 2026-10-11: `?page=N` (0-based), 25 rows per page, newest first; each row is a link `Esityslista N - YYYY` / `Pöytäkirja N - YYYY` to `/asiakirjat/{code}` (agenda rows carry `#paatostiedote`) plus a `Päätöksentekopäivä: d.m.yyyy` line. A year filter exists but its parameter was not visible; not needed — the adapter pages until it passes `since`. Note the listing label can lag the meeting page (council 14/2026 listed as Esityslista while its page was already Pöytäkirja), so stage comes from the meeting page's h1. |
| S2 | Tampere vote format (inline vs attachment) | §7.3 | 2026-10-13, recorded pages (council 10.11.2025 § 176, budget, 19 votes): inline on the item page, under "Äänestystulokset", one header per vote naming the motion and which side was Jaa/Ei, then "Kyllä/Ei/Tyhjä/Poissa N kpl" rows with comma-separated names. No vote attachment. The Kokouskäsittely prose lists motions ("X oli tehnyt seuraavan muutosehdotuksen", numbered "Muutosehdotus N:", "Y kannatti X:n muutosehdotusta", renewed board-stage motions "jotka Z uudisti") and results ("äänin 61-5"). Confidential items are titled "… (Salassa pidettävä)". Fixtures are recorded pages with contact details replaced (`tests/fixtures/tampere/`). |
| S3 | Vantaa vote format | §7.4 | 2026-10-13: prose counts in the Käsittely (with surnames on boards) plus an "Äänestysraportti" attachment per item with each member's choice and party; details in §7.4. |
| S4 | Vantaa transcript index page | §7.4 | |
| S5 | Council member pages with party: Espoo, Tampere | §8 | 2026-10-14: not needed for party. Espoo's council page (www.espoo.fi, robots allows it) shows seats per party and the chairs only, with member lists behind further pages; Tampere's old council URL is a 404. Party comes from S8 instead, and membership from the attendance lists. |
| S6 | Does Helsinki's päätöstiedote stage carry votes? (if yes, votes can appear a week earlier) | §7.1 | 2026-10-11, council 15/2026: no. Entries read "Ehdotuksen mukaan." plus elected names; no counts or ballots. Meetings with a filled päätöstiedote are stored as `stage = decisions`, without votes. |
| S7 | Exact council term start dates per city (assumed 2025-06-01) | §5.2 Term | |
| S8 | Election results download path (Ministry of Justice / StatFin) | §8 | 2026-10-14: Statistics Finland PxWeb, `https://pxdata.stat.fi/PxWeb/api/v1/fi/StatFin/kvaa/{table}.px` (no robots.txt). One table per electoral district, "Ehdokkaiden äänimäärä ja valintatieto kuntavaaleissa": 14uk Helsinki, 14ux Uusimaa (Espoo, Vantaa), 14v2 Pirkanmaa (Tampere), 14uy Varsinais-Suomi, 14v7 Oulu, and so on. Candidate values read `Sukunimi Etunimi / PUOLUE / Kunta`; data is a POST query (CSV) with total votes and Valintatieto 1 = elected, 2 = deputy (varalla), 3 = not elected. The Ministry of Justice results service disallows crawlers in robots.txt, so it is not used. |
| S9 | www.turku.fi robots allows initiative pages | §7.6 | |
| S10 | Espoo page and vote-PDF structure | §7.2 | 2026-10-13, by hand: the §7.2 tables and link shapes hold. `meeting_frames` lists bodies without meetings ("Testitoimielin") as plain text. The meeting page's h1 carries body, stage, date, `klo 17.30 - 19.53` (dot or colon), "⁄ Tarkastettu" and the place; the participants table (Osallistuja / Tehtävä) is present at agenda stage too, so attendance is kept only at minutes stage. Item text opens with `Asianumero …`, `{Body} dd.mm.yyyy § n`, `§ n`, the title and a "Valmistelijat / lisätiedot" table; "Päätösehdotus Esittelijä" is followed by the presenter on its own line, and Päätöshistoria blocks are headed `{Body} dd.mm.yyyy § n` with plain "Käsittely"/"Päätös" lines inside. Votes: Käsittely says "Äänestyksessä valtuusto 30 äänellä 41 ääntä vastaan, 4 äänestäessä tyhjää hylkäsi … Äänestyslista on pöytäkirjan liitteenä."; the first number is the Jaa side. Smaller bodies write numbers as words ("yhden äänestäessä tyhjää"). One vote → attachment "Äänestyslista § n" (layout 1, legend `{Proposer} Jaa / vastaan Ei / Tyhjä`); several → one "Äänestyslistat § n" PDF with `N. Äänestys: Jaa: {label} / Ei: vastaan / Tyhjä` blocks (layout 2; council 8.12.2025 § 167 has six). A deputy can be printed over three lines (`Name`, `(Member replaced)`, `Ei`). Option totals are not in a fixed order. No page headers or footers in the vote PDFs. The build environment could not reach the host, so fixtures are reconstructed (`scripts/make_espoo_fixtures.py`). Recorded pages (2026-10-13, `tests/fixtures/espoo/real/`) add: the item text sits in `div.data-part.meetingitem` under "Kokousasian teksti"; attachments and supplementary material are separate `div.data-part` blocks (the "Liitteet" list inside the text has no links); paragraphs are Word-style `<p><span>` runs, so a heading can share a paragraph with its first sentence ("Päätös Puheenjohtaja totesi …"); item pages are UTF-8, listing and meeting pages ISO-8859-1. |
| S11 | robots.txt of every registry host, especially whether `*.tweb.fi` really disallows (registry README says so; not checked from here) | §18.2 | |
| S12 | Is `*.oncloudos.com` one shared backend? (decides the provider-wide rate cap) | §18.2 | |
| S13 | Real item counts per municipality since 2025-01-01 (replaces the §18.3 estimate) | §18.3 | |
| S14 | Pagefind index size and query latency at ~200k items; fall back to D1 FTS5 if it doesn't hold | §18.4 | |
| S15 | Do municipal hosts block GitHub Actions (Azure) IP ranges? Hyvinkää, Kurikka and Alavus refused automated fetches during research | §18.2 | |

---

### Build log

- 2026-10-17 — Votes for all enabled municipalities (at Savvas's request): `votes_prose` (§7.7) reads votes from the minutes text for the Dynasty and CloudNC municipalities. Audit over the 55 enabled municipalities' stored data with the new reader (votes-audit run 39043922451): of 1,519 minutes items whose text mentions a vote, 1,390 have one (was 672); 2,631 votes (was 1,205), 1,803 with each member's vote (was 1,185), 343 `needs_review` (was 389). The rest are mostly items where the text says a vote was taken but prints no counts (the result sits in an unattached list), name lists the cities print inconsistently, and bare results. Site: a national votes page `/aanestykset/` (every vote in one table, filters by municipality, body type, dates and words, sort by date or margin, JSON and CSV of what is shown), linked from the nav and the home page; vote cards and pages no longer show empty Jaa/Ei labels, and a vote without ballots says the minutes give only counts. Votes reach the R2 municipalities on the next weekly run with `window_weeks: all`. Parainen and the Tweb municipalities are not covered.
- 2026-10-14 — People (part of M5, at Savvas's request): `kunta people --city C` writes `data/{city}/people.json` from the attendance lists (Espoo, Tampere) and Helsinki's council vote tables, with party, result and votes from Statistics Finland's 2025 candidate tables (S8), matched by name key, then accents other than å/ä/ö folded, then a unique surname-plus-subset match; never by fuzzy match, and never creating a person from the election data. Spellings that differ only in accents (Limnéll/Limnell) are one person. The weekly crawl runs it; `people.yml` rebuilds it alone. First run: Helsinki 182 persons, Espoo 309, Tampere 394; councillors left without a party: Espoo 3 (name forms the city prints differently, e.g. Kauste Mika vs Mikki), Tampere 2 (Pursianen-Hautala, a typo in the minutes), Helsinki 5. Site: Espoo and Tampere council and body pages list members from attendance (council: present at half the meetings, or elected in 2025 and present at one of the last three), every vote lists each voter's party as a coloured chip and counts groups by party, and every person has a page (`/{city}/henkilot/{person}/`, built once at the Finnish path like item pages) with party, election result, bodies with attendance, votes with "against group majority", and motions. Speeches stay off person pages (§2.2 rule 9). Person pages add 24 MB to the build. Ballots still carry `person_id = null`; the site joins names at build time, so the §8 acceptance figures wait for the resolver writing ids.
- 2026-10-14 — M4 Vantaa adapter (draft): bodies from the minutes search dropdown (Stadsfullmäktige, regional committees, follow-up groups, the permit section and test bodies excluded), meetings from the minutes and agenda lists, items from the meeting table with §-less rows skipped and presenter initials stripped from titles, item PDFs split into history blocks and the meeting's own block, statements and dissents split off the decision, motions and outcomes from the Käsittely prose, votes paired with the Äänestysraportti attachments (party per voter as `group_text`), board votes with ballots from the surnames in the sentence, and attendance from the cover page or, before 2026, the first pages of the compiled minutes. Pages and PDFs were recorded by `record-pages.yml` (it now takes `#pages=N` to keep long PDFs out of the log); `tests/fixtures/vantaa/` are trimmed recordings with the item and report PDFs re-rendered from their text. Speeches wait for the transcript index spike (S4). Also in this change, the Espoo vote-list gaps from the re-parse: option labels printed after the choice ("Jaa Asian jatkaminen 8"), legends printed above a bare vote number or as a "/"-line inside the voter list, deputies split over two lines ("Laakso Mikko (Sammallahti" / "Tere)"), "J aa", absentees listed but not counted, and a missing Jaa/Ei label no longer flagged when the minutes sentence matches. Live crawl, `kunta stats` and acceptance after merge.
- 2026-10-14 — Vantaa re-crawl after the gap fixes (weekly run on main, `window_weeks: all`): validates with no errors. 11 bodies, 234 meetings, 3,834 items, 106 votes (was 98), 15 `needs_review`, decision coverage 91.1 %, 24 MB. Of 89 items whose Käsittely or decision mentions a vote, 85 have one; of the other 4, two only mention voting (youth council elections, ballot counters), one is a committee's vote quoted in the board's history, and one (board 15.12.2025 § 11) had a full stop for a comma inside the voters' brackets, which ended the result early (fixed in the follow-up). Attendance: 23 minutes-stage meetings still have none, all from the Swedish committee, its education section and the education committee, and none of them publishes a cover page or compiled minutes (19 from 2025, 4 from 2026). People: 249 persons, 196 with a party; the junk names from the old cover parser are gone, except "I" from a board role wrapped after the numeral ("Kasonen Mika, I x …" / "varapuheenjohtaja"), fixed in the follow-up, which also joins a role continued after a comma.
- 2026-10-14 — M4 Vantaa crawl (weekly run, `window_weeks: all`, Espoo alongside): both cities validate without warnings. Vantaa: 11 bodies, 233 meetings, 3,826 items, 98 votes, 14 `needs_review` (8 without a report attachment, 2 without a vote list in the report, 3 where the report's total differs from the sum of its options, 1 where prose and report disagree), decision coverage 90.9 %, 24 MB of data; no §-less row imported as an item. Espoo `needs_review` fell from 54 to 32 with the vote-list fixes. Gaps found and fixed in the follow-up: 9 of 87 items mentioning a vote had none (count orders and spellings the parser missed, a Käsittely cut by a changed proposal) and 32 minutes-stage meetings had no attendance (committee, 2026 board and Swedish cover layouts; about 19 meetings from 2025 publish no cover page or compiled minutes at all). Vantaa joins `people.yml`; the candidate list ("Sukunimi Etunimi") now sets the name order of a matched person, because Vantaa's council covers print deputies first-name first.
- 2026-10-14 — M7 downloads: `kunta export` writes one CSV and one Parquet file per table (bodies, meetings, items, sections, votes, ballots, motions, attendance, persons, memberships) plus `all.zip` with every CSV and a README, and `manifest.json`, to `build/exports/`, with `config/takedowns.yaml` applied (listed items dropped with their votes, ballots and motions; listed strings redacted in every field). Rows sort by their first column in natural order; the zip has a fixed timestamp, so a re-run writes the same bytes. `pages.yml` runs it before the site build and copies the Parquet files, `all.zip` and the manifest to `/data/files/`; `/data/` lists the tables with row counts and sizes. The per-table CSVs stay out of the site (sections alone is 113 MB as CSV). First run over the four enabled cities: 18,688 items, 62,749 sections, 854 votes, 33,586 ballots; `all.zip` 30 MB, Parquet 28 MB, so the downloads add 56 MB to the build (487 MB before Pagefind).
- 2026-10-13 — Full re-parse of Espoo and Tampere with the vote fixes (weekly run 38469534488, `window_weeks: all`; a dispatch with an empty window had silently fallen back to the 10-week default, fixed in PR #11). Both validate clean. Tampere: 83 votes, none `needs_review` (was 48). Espoo: 219 votes (was 165), 54 `needs_review` (was 61). The 54 Espoo flags: 16 where the minutes text and the vote PDF give different counts and 3 where a PDF's total differs from the sum of its options (the city's own inconsistencies, both sides in `review_reason`); 11 with no vote list in the PDF or none attached (prose counts kept); 13 PDF blocks with no Jaa/Ei proposal label; 5 with voter lines the PDF splits mid-name ("Sammallahti Tere)") and 5 whose ballots then do not add up to a count; 1 with no matching vote sentence. The last 24 are parser gaps left for a follow-up; the rest need a human eye. M2 and M3 acceptance holds on Tampere and on the Espoo counts.
- 2026-10-13 — First full live crawls of Espoo and Tampere since 2025-01-01 (weekly run 38420908652), both validating clean, committed and deployed. `kunta stats`: Espoo 19 bodies, 303 meetings, 3,550 items, 165 votes (61 `needs_review`), decision coverage 92.6 %; Tampere 17 bodies, 371 meetings, 4,299 items, 83 votes (48 `needs_review`), decision coverage 99.0 %, attendance on every minutes-stage meeting. Size: data/espoo 27 MB, data/tampere 23 MB raw JSON; the Pages artifact for three cities is 92 MB compressed. An earlier run failed validation on a permit number (`049-2019-881`) read as a phone number, and its data commit was rejected because main moved during the hour-long crawl; both fixed (PR #9). The review flags came from four gaps, fixed in the follow-up PR: Tampere board votes are headed by their two sides ("Esittelijän päätösehdotus JAA, Olga Haapa-ahon muutosehdotus EI") and their result sentences name the presenter's proposal, use "voitti", "Äänestysesityksen tulos" or "tyhjä/tyhjää" (46 of the 48 now match by counts); Espoo vote lists are also titled Äänestystiedot, Äänestystulosraportti or Äänestysraportti (27 flags); Espoo prose also reads "seitsemällä (7) äänellä kuutta (6) vastaan", "kahta vastaan", "JAA ääniä tuli 6 ja EI ääniä 7" and "2 ääntä 1 ollessa poissa vastaan"; and the vote PDF can list votes in another order than the text (council 8.6.2026 § 7), so PDF votes now pair with prose by counts. M2 and M3 acceptance is re-checked on the next crawl.
- 2026-10-13 — M3 Tampere adapter (draft): bodies from the side navigation (`Z/` prefix dropped from the name, youth, elderly, immigrant and substance-abuse councils excluded), meetings from the body page with time and place from the agenda line, meeting page items and three attendance groups (kept at minutes stage), item pages with history per earlier body, presenter, preparers, sections, attachments, motions from the Kokouskäsittely prose and inline votes matched to motions by proposer, kind and number. A vote is `needs_review` when its names do not add up to its counts, or when no prose result matches it. The proxy could not reach the host, so pages were recorded by `record-pages.yml`; `tests/fixtures/tampere/` are those pages, trimmed, with emails and phone numbers replaced. Live crawl and acceptance after merge.
- 2026-10-13 — M2 Espoo adapter (draft): body discovery from `meeting_frames`, all-years meeting listing with stage from the label (the page heading wins only when it already says Pöytäkirja), meeting page (times, place, minutes PDF, items, participants → attendance at minutes stage), item text split by heading lines, history blocks per earlier body, attachments, motions from "X Y:n kannattamana teki/ehdotti/esitti", Cloudmeeting vote PDFs in both layouts paired with the Käsittely prose by order and checked three ways (ballots = PDF totals = prose counts, else `needs_review` with the reason). A vote list that 404s keeps the prose counts with `needs_review`; a 5xx retries later in the run. Listing pages are decoded as UTF-8 when valid, else by the declared charset (Windows-1252 for ISO-8859-1). `weekly.yml` crawls Helsinki and Espoo and takes `cities` and `body` inputs for targeted re-runs. Helsinki loose end: the three council votes flagged "table counts differ" are the city's own inconsistency, each with one member recorded under a different choice in the table than in the minutes text (council 9.9.2026: Ville Merinen, Jaa in the text, Ei in the table). The parser now names the member in `review_reason`, keeps the text's ballots and counts, and takes each member's group from the table, so these votes show groups again.
- 2026-10-12 — Site: Swedish and English UI with a language switcher; all votes as cards per city and year (`/{city}/aanestykset/`); members and party presence on body pages, derived from vote records until M5 (council seats from the latest council vote, members = most-present per group this term); city coats of arms and public-domain/CC0 photos from Wikimedia Commons (`config/images.yaml`, fetched in CI because the build environment cannot reach Wikimedia); city mottos removed. Size with Helsinki data: 219 MB built, up from 183 MB (item pages 102 MB, 14.6 KB each, now with per-member vote dots; sv/en copies of the other pages 17 MB; Pagefind 49 MB). The §13 projection stays under the 700 MB line.
- 2026-10-12 — M1 live: two Helsinki crawls since 2025-01-01. 21 bodies, 532 meetings, 7,013 items, 454 votes (11 `needs_review`, all with a reason). The first run exposed forwarded matters (decision headed Esitys/Lausunto), Swedish section headings and case codes caught as phone numbers; fixed in PR #3. Decision coverage 100 % of public minutes items; the 126 items titled "Salassa pidettävä" (Publicity Act) never get a public decision and are now final, not `needs_refetch`, and are left out of coverage. Size (§13): data/helsinki 72 MB raw JSON (15 MB gzipped); site build 183 MB, of which item pages 90 MB (12.8 KB each) and Pagefind 49 MB, so about 26 KB per item all-in. Projection with §12's 15–25k items for all enabled cities since 2025: 0.4–0.65 GB, under the 700 MB line, so `history` (16 % of section text) stays rendered for now. Helsinki adds about 4k items a year, so re-measure after M2 lands Espoo. Open: three council votes where table and text counts differ.
- 2026-10-11 — M1 Helsinki adapter (draft): body discovery from the committees page and menu, paginated meeting listing, meeting and item pages, HTML vote parser (text blocks paired with the Äänestystulokset tables by order, confirmed by counts; `needs_review` carries a `review_reason`), motions, history sections, crawl loop with a rolling refetch window, transient-error retry, `needs_refetch` state, tombstones after two 404s, layout-change alarm, `weekly.yml` for Helsinki. `kunta/robots.py` replaces `urllib.robotparser`, which ignores the `*` wildcards in paatokset.hel.fi's robots.txt. Parsers key on visible text and URL shapes, not CSS classes. The build environment could not reach paatokset.hel.fi, so `tests/fixtures/helsinki/` are reconstructed from the inspected structure (fictional names, real counts) and must be swapped for recorded pages after the first live run. Meeting pages carry no participant list, so Helsinki attendance waits for M5 (`has_attendance = False`). Size measurement (§13): see 2026-10-12.
- 2026-10-11 — M0 skeleton landed together with a basic site (ahead of M7): city/body/meeting/item routes, `/haku/` (Pagefind), `/data/`, `/tietoa/`, six city themes, Finnish i18n dictionary with room for sv/en. Person, group and case routes wait for M5/M7. A fictional dataset in `site/demo-data/` drives preview builds and CI. Adapters are stubs that raise until their milestone.
- 2026-10-14 — M6 Helsinki speeches (at Savvas's request, after Savvas confirmed the §2.2 rule 9 legal check, so `SPEECHES_BY_PERSON=true`): `kunta speeches --city helsinki` reads each council meeting's transcript PDF (`source_ids.transcript_pdf`, already stored by the crawler) and writes `data/helsinki/speeches/{body}--{date}.json`. The parser takes the table of contents as the list of speeches (item §, agenda number, then each speaker heading) and cuts the body at those headings in order, so a sentence starting "Valtuutettu …" never opens a speech; headings without a title and the typo "Valtutettu" occur. Speakers resolve against people.json by name key, accent fold, a unique surname ("Valtuutettu Helin") or one clear fuzzy match ("Laisaaari"). First run over 33 transcripts (2025-01 to 2026-09): 3,544 speeches of 3,570 contents entries, 99.7 % linked to an item, 98.5 % to a person; nearly all unresolved speakers are youth council representatives, who have no person record. A stored transcript is not re-fetched unless `--refresh`; the weekly crawl runs the command for Helsinki and `speeches.yml` re-parses everything when the parser changes. Site: item pages get a Debate section (each speech collapsed, `#puhe-N` opens one), person pages list the person's speeches with an excerpt linking to the item. Speech JSON is 7 MB; the full build is 435 MB. Vantaa speeches (S4) are not started; the Espoo milestone thread's notes on www.vantaa.fi transcripts are in its thread.

---

## 17. Decisions waiting on humans (defaults in force until changed)

| Topic | Default |
|---|---|
| Site name, domain, contact e-mail for User-Agent | Set 2026-10-11 by Savvas: Kotihiiri, `savvyboi.github.io/kotihiiri`, project contact e-mail in `config/project.yaml`; domain changed to `kotihiiri.eu` on 2026-10-15 (§18.4) |
| Licence for our normalized data | CC BY 4.0, attributing the cities as source |
| Body exclude list (§1) | as written |
| Per-person speech collections | on since 2026-10-14: Savvas confirmed the legal check (§2.2 rule 9) |
| Oulu / Turku | disabled pending written permission |
| Bodies for municipalities 7–96 | council and municipal board first; committees switched on per municipality after M11, once storage is off GitHub |
| Hosts that disallow robots (likely the 13 on `*.tweb.fi`) | disabled pending written permission, as Oulu; Savvas or the team asks Triplan or the municipality |
| Domain for the Cloudflare site | `kotihiiri.eu` (Savvas, 2026-10-15), custom domain of `kotihiiri-site`; `pages.yml` uploads the build there while GitHub Pages keeps serving until M11 accepts |
| Paid fallback | Workers Paid ($5/month) only if D1 or Worker limits bite; nothing in §18 needs it at launch |

---

## 18. Expansion to 96 municipalities (added 2026-10-13)

### 18.1 Registry

`config/registry/municipalities_rank7-96.csv` (90 rows, collected 2026-10-12, column notes and per-platform URL patterns in `config/registry/README.md`). Together with the six cities it covers roughly 85 % of Finland's population. The cut-off around ranks 93–97 is within ~200 people, so re-rank on newer population figures only if the exact set matters.

| Platform | Municipalities | Hosting | Adapter |
|---|---|---|---|
| Dynasty 10 | 47 | 32 on `*.oncloudos.com`, 3 on a regional host (`dynastyjulkaisu.pohjoiskarjala.net`), 2 on `dynasty.voiceintuitive.com`, 10 self-hosted | `dynasty` (Espoo's) |
| Tweb / KTweb | 26 | 13 on `*.tweb.fi`, 4 on `*.triplancloud.fi`, 9 self-hosted | `tweb` (Vantaa's, M4) |
| CloudNC (CaseM) | 10 | all on `*.cloudnc.fi` | `casem` (Tampere's) |
| M-Files Kokoukset | 2 (Imatra, Lappeenranta) | self-hosted | new, M16 |
| Own website or not identified | 5 (Kotka, Korsholm, Hyvinkää, Kurikka, Alavus) | — | spike, M16 |

Verification in the registry: 52 rows live-verified (a council meeting seen), 31 taken from the municipality's own site without fetching, 2 from search results, 5 partial. Only 36 rows have a councillor list URL; M15 fills the rest from election data.

So three adapters we already have (or plan, for Tweb) cover 83 of the 90. The work is generalizing them (base URL, organ ids, host variants) and running them politely at scale, not writing new parsers.

### 18.2 Scraping at 96 municipalities

**Where it runs: GitHub Actions, as now.** Standard runners are free for public repositories, a job may run 6 hours, 20 jobs run at once on GitHub Free and a matrix may hold 256 jobs. The Espoo milestone showed that municipal hosts this build environment can't reach are reachable from Actions.

**Why not Cloudflare for scraping.** Checked 2026-10-13 against Cloudflare's docs: Workers Free gives 10 ms CPU per request, 50 subrequests per invocation and 5 cron triggers per account, and cannot run our Python stack (pdfplumber, selectolax). Containers, which could, need Workers Paid ($5/month, 375 vCPU-minutes included). The crawl is limited by politeness delays, not compute, so moving it gains nothing. One optional later use: a Worker cron that polls Dynasty/Tweb RSS feeds and fires `workflow_dispatch` when something changes, so small municipalities aren't fetched on weeks with no meetings.

**Politeness at scale (adds to §2.1, does not relax it):**
- Rule 4 stays per host. In addition, hosts that share one provider (`*.oncloudos.com`, `*.cloudnc.fi`, `*.tweb.fi`, `*.triplancloud.fi`) get a **provider-wide cap of 2 requests/second** until S12 shows they are separate backends. Thirty-odd subdomains at 1 req/s each would otherwise hit one vendor at 30 req/s.
- The weekly matrix is keyed by **provider group**, not by municipality: one job per shared provider (municipalities inside it run sequentially or interleaved under the cap), plus one job per batch of self-hosted municipalities. That keeps the job count under 20 and lets each job enforce its own cap.
- robots.txt is checked per host on every run as now; the M10 audit only decides the starting `enabled` flag. The registry README says `*.tweb.fi` hosts disallow crawlers; if S11 confirms it, 13 municipalities (Hämeenlinna, Rauma, Kerava, Nokia, Kangasala, Pirkkala, Valkeakoski, Varkaus, Akaa, Janakkala, Kuusamo, Ilmajoki, Muurame) ship disabled like Oulu. No workarounds.
- Statistics Finland's PxWeb API is for the councillor seed (M15). The Ministry of Justice results service disallows crawlers and is not used.

**Sizing (estimate, replaced by S13):** a municipality of 10–50k people holds roughly 60–100 meetings a year across council, board and a handful of committees, ~700–1,500 items. Across the 90 that is ~80–110k items a year, so ~150–200k items since 2025-01-01 by the end of 2026, plus ~25k for the six cities. Backfill of one provider group at 2 req/s: `*.oncloudos.com` (~33 municipalities × ~3k requests) ≈ 14 hours, split over three nights by `backfill.yml`. The weekly run with the 10-week refetch window is ~200 requests per small municipality, about an hour for the largest group.

**Raw cache.** `.cache/raw` can't stay in `actions/cache` (10 GB per repo). Conditional GETs only need the validators, which live in state; a 304 means the stored JSON is still right. The raw cache becomes optional and per-run.

### 18.3 Why GitHub Pages and git storage stop working

Measured on the six-city build (build log 2026-10-12/13): ~26 KB of built site per item and 5–10 KB of canonical JSON per item. At ~200k items:
- built site ≈ 5 GB against Pages' 1 GB limit;
- canonical JSON ≈ 1–2 GB, growing ~0.7 GB a year, against the 1 GB repo guideline, and every weekly change adds history;
- file count far over 20,000, so Cloudflare Pages Free and Workers Static Assets Free (both capped at 20,000 files per deployment) can't host it as static files either.

### 18.4 Target hosting: Cloudflare Free, R2-first

Limits checked 2026-10-13: R2 Free has 10 GB-month storage, 1M Class A (writes) and 10M Class B (reads) operations a month, and free egress, with no file-count limit. D1 Free: 500 MB per database, 10 databases, 5 GB total, 5M rows read and 100k rows written a day. Workers Free: 100k requests a day, 10 ms CPU.

```
GitHub Actions (public repo, free runners)
 ├─ weekly / monthly / backfill   crawl per provider group → parse → validate
 │                                  → canonical JSON + state  →  R2 bucket kotihiiri-data (private)
 ├─ build                          Astro static build from R2 data → Pagefind
 │                                  → rclone sync --checksum      →  R2 bucket kotihiiri-site (public)
 └─ exports                        parquet/csv/zip                 →  kotihiiri-site/data/ + monthly GitHub Release

Cloudflare (free zone on Savvas's domain)
 R2 custom domain on kotihiiri-site → CDN cache → visitors
 Transform rule: path ending in "/" → append "index.html"
```

- **Pages stay static.** The build still renders every page ahead of time, so nothing runs per request: no Worker CPU limit, no daily request cap, and the CDN caches pages so most views cost no R2 reads. Uploads are only the files whose checksum changed, which keeps weekly Class A operations in the low thousands; the first full upload (~250k files) fits inside one month's 1M.
- **Storage.** ~5 GB built site + ~1.5 GB JSON fits the 10 GB free tier into 2027; beyond it R2 costs $0.015/GB-month, a few cents.
- **Search.** Pagefind's chunked index is static files and works from R2; S14 checks size and speed at full scale. Fallback: a Worker over D1 FTS5 split per region (500 MB per database), which uses the Worker request cap only for searches.
- **Why a domain.** R2 serves public buckets at production quality only through a custom domain on a Cloudflare zone (the `r2.dev` URL is rate-limited and meant for testing). Without a domain the fallback is a Worker on `workers.dev` that streams pages from R2; that works on the free plan but every page view then counts against the 100k-requests-a-day cap.
- **Determinism (§2.2 rule 10) carries over:** a no-change run must write zero objects to R2. The repository keeps code, config and a small weekly change manifest (`data/state/changes/{iso-week}.jsonl`: ids and content hashes), so git still shows what changed without holding the data.
- **Transition.** Six-city data stays in git and Pages keeps serving until M11 accepts; M12+ municipalities only ever land in R2.

### 18.5 Site and data-model changes

- Home page: 96 municipalities don't fit as cards. Search-as-you-type list plus a region filter (maakunta); the six city themes stay, the rest share one neutral theme. No images or coats of arms for the 90 for now (Savvas, 2026-10-15).
- Glossary (§0) additions: kunnanvaltuusto / kunnanhallitus (municipal council / board, `council` / `board`), and Swedish forms for Swedish-majority municipalities (Raseborg, Jakobstad, Pedersöre, Korsholm, Mariehamn): fullmäktige, stads-/kommunstyrelse, nämnd, föredragningslista, protokoll, omröstning, Ja / Nej / Blankt / Frånvarande. The §1 exclusion of Swedish *duplicates* stays; where Swedish is the only or primary language of the minutes, those are the documents, stored with `lang = sv`.
- Mariehamn sits under Åland's own municipal law and elections; its council roster comes from the town's own pages, not StatFin.
- §13 size budget (700 MB) applies only while on Pages.

### 18.6 Steps only Savvas can do

1. Create a Cloudflare account (free plan) and enable R2. R2 asks for a payment method even on the free tier; nothing is charged inside the free allowances.
2. Create two R2 buckets: `kotihiiri-data` (private) and `kotihiiri-site`.
3. Register a domain (e.g. a `.fi`) at any registrar and add it to Cloudflare as a free zone, then connect it to `kotihiiri-site` as the bucket's custom domain. Update `site_domain` in `config/project.yaml`, which also changes the crawler's User-Agent.
4. Create an R2 API token (Object Read & Write, both buckets) and add GitHub repository secrets `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
5. Decide whether to ask Triplan (or the 13 municipalities) for crawl permission if S11 confirms the `*.tweb.fi` disallow.
