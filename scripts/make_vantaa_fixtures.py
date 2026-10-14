"""Render tests/fixtures/vantaa/doc-*.txt as PDFs (doc-*.pdf) for the Vantaa adapter tests.

The .txt files are the text of public documents recorded from paatokset.vantaa.fi on 2026-10-13
by scripts/record_pages.py, with contact details replaced; "--- page N" lines mark page breaks.
Needs `reportlab`.
"""

from __future__ import annotations

import io
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "vantaa"


def pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    y = 810
    started = False
    for line in lines:
        if line.startswith("--- page "):
            if started:
                c.showPage()
            y, started = 810, True
            continue
        if y < 40:
            c.showPage()
            y = 810
        c.setFont("Helvetica", 7)
        c.drawString(20, y, line)
        y -= 10
    c.showPage()
    c.save()
    return buf.getvalue()


def main() -> None:
    for src in sorted(FIXTURES.glob("doc-*.txt")):
        src.with_suffix(".pdf").write_bytes(pdf(src.read_text(encoding="utf-8").splitlines()))
        print(src.with_suffix(".pdf").name)


if __name__ == "__main__":
    main()
