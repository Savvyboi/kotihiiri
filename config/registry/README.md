# Finnish municipal councils — source registry (population ranks 7–96)

90 municipalities: the largest after Helsinki, Espoo, Tampere, Vantaa, Oulu and Turku, ranked by Statistics Finland's preliminary population of 31 Mar 2025 (Jyväskylä #7 … Sotkamo #96). Next in line: Lieksa (#97, 10,009), Ii, Masku. The cut-off is tight around #93–97 (Liminka, Kauniainen, Sotkamo, Lieksa are within ~200 people), so re-rank on the latest figures if the exact set matters.

Collected 12 Oct 2026. File: `municipalities_rank7-96.csv` (the research also came as JSON with the same rows; only the CSV is kept). How the registry is used: PLAN.md §18.

## Columns

| column | meaning |
|---|---|
| `platform` | Dynasty 10 · Tweb / KTweb · CloudNC (CaseM) · M-Files Kokoukset · other |
| `portal_url` | entry page of the agenda/minutes system |
| `council_meetings_url` | the council's (valtuusto) meeting list where the organ ID was confirmed; for Tweb, the agenda search page |
| `minutes_search_url` | Tweb minutes search (`pk_tek_tweb.htm`) |
| `councillors_url` | best member list found: city page, Tweb `lumu_organ.htm` registry, or other register |
| `rss_url` | Dynasty item feed (see caveat below) |
| `officials_decisions_url` | viranhaltijapäätökset |
| `verification` | `live-verified` = system page fetched and council meetings seen (date in `latest_council_meeting_seen`); `linked-from-official-site` = URL taken from the municipality's own site, not fetched; `search-index` = only seen in search results; `partial` = system not identified |

Tweb `lumu_organ.htm`, `pk_tek_tweb.htm` and `vparhaku_tweb.htm` URLs are derived from the standard Tweb path layout, not individually opened.

## Platform URL patterns

**Dynasty 10** (47 municipalities; `*.oncloudos.com` cloud or self-hosted `…/cgi/DREQUEST.PHP`)
- organs: `?page=meeting_frames` · all organs: `?page=meeting_handlers&id=`
- organ meeting list: `?page=meetings&id=<organ_id>` (council IDs in the CSV)
- meeting: `?page=meeting&id=<meeting_id>` → attendance table (Osallistuja/Tehtävä) + item list
- item: `?page=meetingitem&id=<meeting_id>-<n>` → proposal, decision, decision history; votes appear in the decision text only when a vote was taken
- full PDF: `/kokous/<meeting_id>.PDF` (variants `-<n>` per item)
- feeds: `?page=rss/meetingitems&show=30`, `?page=rss/meetings&show=30` — output is malformed XML (no `<rss>/<item>` wrappers), parse leniently
- officials: `?page=official_frames`

**Tweb / KTweb** (26; `*.tweb.fi`, `*.triplancloud.fi`, or self-hosted, sometimes under `/ktwebbin/dbisa.dll/`)
- agendas `ktwebscr/epj_tek_tweb.htm`, minutes `ktwebscr/pk_tek_tweb.htm`, meeting agenda `epj_asil_tweb.htm?bid=<id>`, organ minutes `pk_kokl_tweb.htm`
- members/trustee registry `ktwebscr/lumu_organ.htm`, notices `kuullist_tweb.htm`, officials `vparhaku_tweb.htm`
- tweb.fi hosts disallow crawlers in robots.txt

**CloudNC (CaseM)** (10; `<kunta>.cloudnc.fi`)
- organs `/fi-FI/Toimielimet`, organ `/fi-FI/Toimielimet/<Organ_Name>`, meeting `/fi-FI/Toimielimet/<Organ>/Kokous_<D><M><YYYY>` (no zero padding, e.g. `Kokous_2892026`)
- documents `/download/noname/{<guid>}/<id>`; umlauts in organ slugs become `aumlauml`-style (`Ympaumlristoumllautakunta`)

**M-Files Kokoukset** (Imatra, Lappeenranta): `/kokoukset/<kunta>/<organ_id>`

## Councillor lists — national sources

- Statistics Finland, municipal elections 13 Apr 2025 (elected councillors, party, municipality): https://pxdata.stat.fi/PxWeb/pxweb/fi/StatFin/StatFin__kvaa/ (PxWeb API: `https://pxdata.stat.fi/PxWeb/api/v1/fi/StatFin/kvaa/`)
- Ministry of Justice results service: https://tulospalvelu.vaalit.fi/KV-2025/ (candidate-level results; robots.txt blocks crawlers)
- Mariehamn is on Åland and is not in the national municipal-election data.
- Term 1 Jun 2025 – 31 May 2029; replacements (varavaltuutetut stepping in) only show up in minutes / Tweb `lumu_organ`.

## Open items

- **Hyvinkää** – decision system not identified (site refused automated fetches).
- **Kotka** – new system since 3 Nov 2025 not identified; 2024–2025 PDFs in an open directory index.
- **Kurikka, Alavus** – external system link not visible to automated fetch.
- **Korsholm** – publishes on its own site (FI/SV); Suomi.fi still lists a legacy Tweb host.
