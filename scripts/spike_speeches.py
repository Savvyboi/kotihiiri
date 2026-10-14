"""Spike (M6): print the text layout of two Helsinki council transcripts to the job log.
Nothing is written to the repo. Removed once the parser lands."""

import re
import sys

from kunta.config import load_project
from kunta.http import PoliteClient
from kunta.pdf import drop_repeated_lines, pdf_pages

urls = sys.argv[1:]
with PoliteClient(load_project().user_agent, allowed_hosts={"paatokset.hel.fi"}) as c:
    for url in urls:
        raw = pdf_pages(c.get(url).content)
        pages = drop_repeated_lines(raw)
        print(f"=== {url}: {len(raw)} pages")
        print("--- page 1 raw"); print("\n".join(raw[0]))
        print("--- page 2 raw"); print("\n".join(raw[1]))
        print("--- removed header/footer lines of page 3")
        print("\n".join(ln for ln in raw[2] if ln not in pages[2]))
        lines = [ln for p in pages for ln in p]
        print(f"--- {len(lines)} lines; lines 0-400 after header removal")
        for i, ln in enumerate(lines[:400]):
            print(f"{i:4} {ln}")
        print("--- candidate headings over the whole file")
        pat = re.compile(r"^(\d+ ?§|Esityslistan asia|Valtuutettu|Ledamoten|Apulaispormestari|Pormestari|Puheenjohtaja|Biträdande|Borgmästare|Ordförande)")
        for i, ln in enumerate(lines):
            if pat.match(ln.strip()):
                print(f"{i:5} {ln}")
