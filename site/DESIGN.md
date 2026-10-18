# Kotihiiri look: "vaakuna"

The site takes its look from Finnish municipal coats of arms, which every municipality page
already shows. Five decisions, made once; change them here first, then in `src/styles/`.

1. **Theme.** Finnish civic heraldry: flat tinctures, no shading, a few large clear shapes. The
   site is a public record, so it reads like a printed register rather than an app. No gradients
   except the shade that keeps text readable over a city photo.
2. **Colour.** Two metals and one colour, as in a coat of arms. Argent paper (`--c-bg #f4f4f0`),
   sable ink (`--c-text #15171c`), and one tincture per page: heraldic azure `#1d3f73` for the
   national pages, the city's own colour on city pages (`themes.css`). Gold (`--c-or`) is the only
   second accent: the current page in navigation. Vote colours stay vert (jaa) and gules (ei).
3. **Type.** Bitter (slab serif) for headings, the brand and figures: sturdy like lettering on a
   municipal sign, and its numerals read well large. Source Sans 3 for text and tables. Both are
   self-hosted from npm (`@fontsource-variable/*`), so no font request leaves the site.
4. **Layout.** One 1120 px column. Navigation is a text bar with a gold underline for the current
   page, not pills. Pages open with a tinted header that ends in a fir-tree-top line
   (`--koro`, the *kuusikoro* partition Finnish heraldry invented); city cards use the same line
   between photo and name.
5. **Tone.** Square corners (`--radius: 3px`), 1 px rules instead of shadows, a 2 px ink rule under
   table headings and above the footer, no hover lift, no all-caps labels. Quiet and exact.
