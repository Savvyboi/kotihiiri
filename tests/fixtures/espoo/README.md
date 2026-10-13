# Espoo fixtures

**Reconstructed, not recorded.** The environment that built M2 could not reach
espoo.oncloudos.com, so these pages and vote PDFs were rebuilt from the structure inspected by
hand on 2026-10-13 (PLAN.md §16 S10): table headers, link shapes, heading lines, Käsittely
sentences and both Cloudmeeting Äänestystulosraportti layouts. Member names are fictional;
counts follow the real items (council 21.9.2026 § 132: Jaa 30 / Ei 41 / Tyhjä 4; council
8.12.2025 § 167: six votes). Listing pages are ISO-8859-1 like the real ones.

Regenerate with `python scripts/make_espoo_fixtures.py` (needs `reportlab`).

## Recorded pages (`real/`)

`real/` holds four pages fetched from espoo.oncloudos.com on 2026-10-13 with
`scripts/record_pages.py` (public documents): council 20.1.2025 (meeting page, § 1 and § 7 with
three votes) and council 21.9.2026 § 132. The markup is compacted (scripts, styles and attributes
other than href/class/id removed) and stored as UTF-8. They pin the real item layout the
reconstructed pages missed: the item text sits in `div.data-part.meetingitem`, attachments and
supplementary material in their own `div.data-part` blocks, and a heading can share a paragraph
with its first sentence. The vote PDFs are still the generated ones; the real § 132 PDF matched
layout 1 line for line when inspected.
