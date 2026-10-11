# Helsinki fixtures

**Reconstructed, not recorded.** The environment that built M1 could not reach
paatokset.hel.fi, so these pages were rebuilt from the structure inspected by hand on
2026-10-11 (heading texts, labels, link shapes, pager, vote text blocks and Äänestystulokset
tables). Member names are fictional; counts and labels follow the real item HEL 2026-008342
(council 23.9.2026 § 261: 34 Jaa / 36 Ei / 15 Tyhjä / 0 Poissa).

Regenerate with `python scripts/make_helsinki_fixtures.py`.

After the first live crawl, replace them with the real pages from `.cache/raw/paatokset.hel.fi/`
(public documents; keep each under 1 MB, PLAN.md §14), re-run
`pytest --update-goldens`, and check the golden diff by hand.
