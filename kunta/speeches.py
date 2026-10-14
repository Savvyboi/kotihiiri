"""`kunta speeches`: speech transcripts per meeting (PLAN.md §5.3, M6).

Helsinki publishes one transcript PDF per council meeting; its URL is stored on the meeting as
`source_ids.transcript_pdf`. Each meeting's speeches go to
`data/{city}/speeches/{body_slug}--{date}.json`. A transcript does not change once published, so a
meeting whose speeches file exists is skipped unless `refresh` is set. Speakers are resolved
against `data/{city}/people.json`; a name that matches no one, or more than one person, keeps
`person_id` empty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from . import jsonio
from .config import DATA_DIR
from .http import FetchFailed, PoliteClient
from .ids import speeches_file_path
from .models import Speech
from .parsers import speeches_helsinki
from .pdf import drop_repeated_lines, pdf_pages
from .people import name_key
from .roster import _fold

log = logging.getLogger(__name__)


@dataclass
class Report:
    meetings: int = 0
    skipped: int = 0
    speeches: int = 0
    expected: int = 0
    linked_item: int = 0
    linked_person: int = 0
    failures: list[str] = field(default_factory=list)
    unresolved: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        pct = lambda n: f"{100 * n / self.speeches:.1f} %" if self.speeches else "–"  # noqa: E731
        return (
            f"speeches: meetings={self.meetings} skipped={self.skipped} speeches={self.speeches} "
            f"(contents list {self.expected}) linked_item={pct(self.linked_item)} "
            f"linked_person={pct(self.linked_person)} failures={len(self.failures)}"
        )


class Resolver:
    """Speaker name ("Etunimi Sukunimi", sometimes the surname alone or with a typo) → person id."""

    def __init__(self, people: dict) -> None:
        self.by_key: dict[str, str | None] = {}
        self.by_surname: dict[str, str | None] = {}
        for p in people.get("persons", []):
            for n in {p["name"], p["sort_name"], *p.get("aliases", [])}:
                self._add(self.by_key, _fold(name_key(n)), p["id"])
            sort = p["sort_name"].split(" ")
            for surname in {p["name"].partition(" ")[2], " ".join(sort[:-1]), sort[0]}:
                self._add(self.by_surname, _fold(name_key(surname)), p["id"])

    @staticmethod
    def _add(index: dict[str, str | None], key: str, pid: str) -> None:
        index[key] = pid if index.get(key, pid) == pid else None

    def resolve(self, raw: str) -> tuple[str | None, float | None]:
        key = _fold(name_key(raw))
        if key in self.by_key:
            return self.by_key[key], 1.0 if self.by_key[key] else None
        if self.by_surname.get(key):
            return self.by_surname[key], 0.8
        # One doubled or dropped letter ("Laisaaari"): accept a single clear winner.
        scored = sorted(
            ((fuzz.ratio(key, k), pid) for k, pid in self.by_key.items() if pid),
            reverse=True,
        )
        if scored and scored[0][0] >= 92 and (len(scored) == 1 or scored[1][0] < scored[0][0] - 3):
            return scored[0][1], round(scored[0][0] / 100, 2)
        return None, None


def _items(mf: dict) -> dict[int, tuple[str, int | None]]:
    return {i["ordinal"]: (i["id"], i.get("pykala")) for i in mf["items"]}


def run(
    city: str,
    client: PoliteClient,
    since: str = "2025-01-01",
    refresh: bool = False,
    data_dir: Path = DATA_DIR,
) -> Report:
    if city != "helsinki":
        raise NotImplementedError(f"{city}: no speech source yet (PLAN.md M6 covers Helsinki)")
    report = Report()
    people_path = data_dir / city / "people.json"
    resolver = Resolver(jsonio.read(people_path) if people_path.exists() else {})
    for path in sorted((data_dir / city / "meetings").glob("*/*.json")):
        mf = jsonio.read(path)
        m = mf["meeting"]
        url = m.get("source_ids", {}).get("transcript_pdf")
        if not url or m["date"] < since:
            continue
        out = data_dir / speeches_file_path(m["id"])
        if out.exists() and not refresh:
            report.skipped += 1
            speeches = [Speech.model_validate(s) for s in jsonio.read(out)]
        else:
            try:
                pages = drop_repeated_lines(pdf_pages(client.get(url).content))
            except FetchFailed as exc:
                report.failures.append(f"{url}: {exc}")
                continue
            speeches, expected = speeches_helsinki.parse_transcript(
                [ln for p in pages for ln in p], m["id"], _items(mf), url
            )
            report.expected += expected
            if expected and len(speeches) < expected:
                log.warning("%s: %d of %d speeches found", url, len(speeches), expected)
        report.meetings += 1
        for s in speeches:
            pid, conf = resolver.resolve(s.speaker_ref.raw)
            s.speaker_ref.person_id, s.speaker_ref.confidence = pid, conf
            if pid:
                report.linked_person += 1
            else:
                report.unresolved[s.speaker_ref.raw] = report.unresolved.get(s.speaker_ref.raw, 0) + 1
            report.linked_item += s.item_id is not None
        report.speeches += len(speeches)
        if speeches:
            jsonio.write(out, speeches)
    return report
