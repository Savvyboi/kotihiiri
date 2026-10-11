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

UI strings live in `site/src/i18n/fi.ts`. To add Swedish or English, copy it to `sv.ts`/`en.ts`
(the `Dict` type forces the same keys), register it in `site/src/i18n/index.ts` and add the
locale to `site/src/i18n/locales.js`. Finnish stays at the root; other locales get `/sv/`, `/en/`.

### City themes

Each city page sets `data-city` on `<html>`; colours are CSS custom properties in
`site/src/styles/themes.css`, and each city's motif and motto are in `site/src/lib/themes.ts`.

| City | Palette | Drawn from |
|---|---|---|
| Helsinki | blue `#0000bf`, gold | the sea and the crown on the city arms |
| Espoo | forest green `#00664a`, amber | Nuuksio forests |
| Tampere | brick red `#8c2318`, navy | red-brick mills and Tammerkoski |
| Vantaa | river teal `#006b7a`, coral | Vantaanjoki and the airport |
| Oulu | tar navy `#1b2a41`, aurora green | tar trade and northern lights |
| Turku | crimson `#9e1b32`, gold | the city arms and the cathedral |

These are drafts; check them against each city's official brand guidelines before launch.

## Deployment

`.github/workflows/pages.yml` builds `site/` and deploys to GitHub Pages on every push to `main`.
Enable Pages with source "GitHub Actions" in the repository settings.

## Licence

Normalized data: CC BY 4.0, attributing the cities as source (PLAN.md §17). Code licence not yet chosen.
