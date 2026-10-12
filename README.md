# Kotihiiri

What the city councils of Finland's six largest cities decide, how members vote and what they
say. A static site on GitHub Pages, fed by a polite weekly scraper. Inspired by
[mijnkamer.be](https://mijnkamer.be/), adapted from the Belgian parliament to Finnish city
councils (kaupunginvaltuusto), boards and committees.

**The build spec is [PLAN.md](PLAN.md).** Hard constraints are in §2; milestones in §15.

## Status

| Milestone | State |
|---|---|
| M0 Skeleton: package, polite HTTP client, models, IDs, deterministic JSON, CI | done |
| Basic site: Astro, city themes, Finnish i18n, city/body/meeting/item pages, search | done (ahead of M7) |
| M1 Helsinki adapter, weekly crawl | built against fixtures; first live crawl runs from `weekly.yml` after merge |
| M2 Espoo … M8 operations | not started |

Oulu and Turku are disabled in `config/cities.yaml` until the cities give written permission.

## Layout

```
config/          project settings, cities, per-city body overrides, takedowns
kunta/           Python package (scraper + CLI); adapters are stubs until their milestone
data/            canonical committed JSON (empty until M1)
site/            Astro site; reads ../config and ../data at build time
site/demo-data/  fictional dataset for previews and CI (marked with a DEMO file)
tests/           pytest suite
```

## Python

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest && ruff check .
kunta stats
kunta validate
```

`kunta crawl` refuses to run until `site_domain` and `contact_email` are set in
`config/project.yaml`, because both go into the User-Agent (PLAN.md §2.1).

## Site

```sh
cd site
npm ci
npm run dev                            # uses ../data (empty pages until M1)
KUNTA_DATA_DIR=demo-data npm run dev   # fictional demo data, with a banner saying so
npm run build                          # static build + Pagefind index in site/dist
```

Regenerate the demo data with `python scripts/make_demo_data.py`.

### Languages

The interface is in Finnish (site root), Swedish (`/sv/`) and English (`/en/`); city documents are
shown as the city publishes them. UI strings live in `site/src/i18n/{fi,sv,en}.ts` (the `Dict` type
forces the same keys). Pages live under `site/src/pages/[...lang]/` and are built once per locale,
except item pages: there are thousands of them, so they are built once at the Finnish path and
translated client-side when opened with `?lang=sv` or `?lang=en` (`SharedI18n.astro`). Without
JavaScript they stay in Finnish.

### City themes

Each city page sets `data-city` on `<html>`; colours are CSS custom properties in
`site/src/styles/themes.css`. Coats of arms and hero photos come from Wikimedia Commons:
`config/images.yaml` names them, `.github/workflows/city-images.yml` runs
`scripts/fetch_city_images.py` on the branch that changes the config and commits the files to
`site/public/images/cities/` with source, author and licence in `site/src/data/city-images.json`
(also listed on `/tietoa/`). Arms come from each city's Wikidata item; photos are pinned files
whose Commons licence is public domain or CC0.

| City | Palette | Photo |
|---|---|---|
| Helsinki | blue `#0000bf`, gold | Helsinki Cathedral |
| Espoo | forest green `#00664a`, amber | Dipoli, Otaniemi |
| Tampere | brick red `#8c2318`, navy | Tammerkoski |
| Vantaa | river teal `#006b7a`, coral | St Lawrence's Church |
| Oulu | tar navy `#1b2a41`, aurora green | Market square |
| Turku | crimson `#9e1b32`, gold | Aura river, Martinsilta and the Cathedral |

### Votes, members and parties

`/{city}/aanestykset/` shows every vote as a card (one page per year, filterable by body and
result). Body pages list who sits on the body and the party presence. Until the roster scraper
lands (PLAN.md §8, M5) both are derived from vote records in `site/src/lib/people.ts`: council
seats per group come from the latest council vote, and the members are the people who took part in
the most votes of the current term; other bodies list everyone seen in their votes, with the
council group where the person is a councillor.

## Deployment

`.github/workflows/pages.yml` builds `site/` and deploys to GitHub Pages on every push to `main`.
Enable Pages with source "GitHub Actions" in the repository settings.

## Licence

Normalized data: CC BY 4.0, attributing the cities as source (PLAN.md §17). Code licence not yet chosen.
