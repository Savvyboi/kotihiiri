# Espoo fixtures

**Reconstructed, not recorded.** The environment that built M2 could not reach
espoo.oncloudos.com, so these pages and vote PDFs were rebuilt from the structure inspected by
hand on 2026-10-13 (PLAN.md §16 S10): table headers, link shapes, heading lines, Käsittely
sentences and both Cloudmeeting Äänestystulosraportti layouts. Member names are fictional;
counts follow the real items (council 21.9.2026 § 132: Jaa 30 / Ei 41 / Tyhjä 4; council
8.12.2025 § 167: six votes). Listing pages are ISO-8859-1 like the real ones.

Regenerate with `python scripts/make_espoo_fixtures.py` (needs `reportlab`).

After the first live crawl, replace them with real pages from `.cache/raw/espoo.oncloudos.com/`
(public documents; keep each under 1 MB, PLAN.md §14), re-run `pytest --update-goldens`, and
check the golden diff by hand.
