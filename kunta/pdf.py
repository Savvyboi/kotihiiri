"""PDF → text helpers (PLAN.md §9). pdfplumber is imported lazily."""

from __future__ import annotations

import io
import re
from collections import Counter

_PAGE_NO = re.compile(r"\b\d+\s*/\s*\d+\b|\b\d+\s*\(\s*\d+\s*\)")


def _key(line: str) -> str:
    # Page counters ("3 / 12") vary per page; compare lines with them masked.
    return _PAGE_NO.sub("#", line.strip())


def drop_repeated_lines(pages: list[list[str]], threshold: float = 0.5) -> list[list[str]]:
    """Remove header/footer lines that recur on at least `threshold` of the pages."""
    if len(pages) < 2:
        return pages
    counts = Counter(k for page in pages for k in {_key(ln) for ln in page if ln.strip()})
    limit = max(2, int(len(pages) * threshold + 0.999))
    repeated = {k for k, n in counts.items() if n >= limit}
    return [[ln for ln in page if _key(ln) not in repeated] for page in pages]


def join_lines(lines: list[str]) -> str:
    """Re-join hyphenated breaks when the next line starts lowercase; keep blank-line paragraphs."""
    out: list[str] = []
    for ln in lines:
        ln = ln.rstrip()
        if out and out[-1].endswith("-") and ln[:1].islower():
            out[-1] = out[-1][:-1] + ln
        else:
            out.append(ln)
    return "\n".join(out)


def pdf_pages(data: bytes, max_pages: int | None = None) -> list[list[str]]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [(page.extract_text() or "").splitlines() for page in pdf.pages[:max_pages]]


def pdf_text(data: bytes) -> str:
    pages = drop_repeated_lines(pdf_pages(data))
    return "\n\n".join(join_lines(p) for p in pages).strip()
