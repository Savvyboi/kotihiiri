# Vantaa fixtures

Recorded from paatokset.vantaa.fi on 2026-10-13 with `scripts/record_pages.py` (public
documents). HTML pages are compacted (scripts, styles and attributes other than
href/class/id/value removed) and stored as UTF-8; the site serves them as ISO-8859-1 with
Windows-1252 dashes. The two minutes lists are cut to the recorded meetings plus one row from
before 2025.

`doc-*.txt` hold the text of item, cover-page and vote-report PDFs as pdfplumber extracted it
("--- page N" marks a page break); `doc-*.pdf` are rendered from them with
`python scripts/make_vantaa_fixtures.py` (needs `reportlab`). Contact lines have their phone
numbers replaced. `doc-3291113` is only the first four pages of the 17.11.2025 compiled minutes
(table of contents and cover page).

| Fixture | What |
|---|---|
| `meeting-161950`, `doc-3460149` | council 21.9.2026, cover page with two-column attendance |
| `meeting-160586`, `doc-3291113` | council 17.11.2025 (budget session), no cover row |
| `doc-3263227`, `doc-3265562` | budget § 9: board block with surnames in the vote sentences, council block with six votes and their report |
| `doc-3263229`, `doc-3265564` | tax rates § 10: one vote and its report |
| `doc-3256569` | the board's 4.11.2025 § 6 vote report (attached to the council item too) |
| `meeting-161913`, `doc-3461024` | board 21.9.2026, cover page with an unmarked deputy column |
| `agenda-161954`, `agenda-161917` | upcoming agendas |
| `doc-3460153` | § 1 procedural item, served for documents not recorded |
