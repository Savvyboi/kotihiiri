"""Validation of committed data (PLAN.md §10). Errors fail the city; warnings are reported."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from . import jsonio
from .config import DATA_DIR
from .models import MeetingFile, Speech
from .text import contains_pii

PARSE_ERROR_ALARM_RATIO = 0.05


@dataclass
class Report:
    city: str
    files: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _texts(mf: MeetingFile):
    for item in mf.items:
        yield item.id, item.title
        for s in item.sections + item.statements:
            yield item.id, s.text
        for m in item.motions:
            yield item.id, m.text
        if item.decision_summary:
            yield item.id, item.decision_summary


def validate_meeting_file(path: Path, report: Report, has_attendance: bool = True) -> None:
    try:
        mf = MeetingFile.model_validate(jsonio.read(path))
    except (ValidationError, ValueError) as exc:
        report.errors.append(f"{path}: schema: {exc}".splitlines()[0])
        return
    if not mf.meeting.source_url:
        report.errors.append(f"{mf.meeting.id}: meeting without source_url")
    if mf.meeting.stage == "minutes" and not mf.meeting.attendance and has_attendance:
        report.warnings.append(f"{mf.meeting.id}: minutes without attendance")
    for item in mf.items:
        if not item.source_url:
            report.errors.append(f"{item.id}: missing source_url")
        if not item.title.strip():
            report.errors.append(f"{item.id}: empty title")
        for v in item.votes:
            got = Counter(b.choice for b in v.ballots)
            if (
                v.ballots
                and any(got.get(c, 0) != getattr(v.counts, c) for c in ("jaa", "ei", "tyhja", "poissa"))
                and not v.needs_review
            ):
                report.warnings.append(f"{item.id} vote {v.ordinal}: ballots ≠ counts, needs_review not set")
            if v.needs_review and not v.review_reason:
                report.warnings.append(f"{item.id} vote {v.ordinal}: needs_review without a reason")
    for item_id, text in _texts(mf):
        if contains_pii(text):
            report.errors.append(f"{item_id}: e-mail or phone number in stored text")


def _has_attendance(city: str) -> bool:
    """Whether the city's adapter publishes attendance at all (Helsinki's pages do not)."""
    from .adapters import ADAPTERS
    from .config import load_cities

    cfg = load_cities().get(city)
    return getattr(ADAPTERS.get(cfg.adapter) if cfg else None, "has_attendance", True)


def validate_city(city: str, data_dir: Path = DATA_DIR) -> Report:
    report = Report(city)
    has_attendance = _has_attendance(city)
    for path in sorted((data_dir / city / "meetings").glob("*/*.json")):
        report.files += 1
        validate_meeting_file(path, report, has_attendance)
    for path in sorted((data_dir / city / "speeches").glob("*.json")):
        report.files += 1
        try:
            for s in jsonio.read(path):
                sp = Speech.model_validate(s)
                if contains_pii(sp.text):
                    report.errors.append(f"{sp.id}: e-mail or phone number in speech")
        except (ValidationError, ValueError) as exc:
            report.errors.append(f"{path}: schema: {exc}".splitlines()[0])
    return report


def layout_alarm(meetings_per_active_body: dict[str, int], fetched: int, parse_errors: int) -> list[str]:
    """§10: an active body dropping to zero meetings or >5 % parse errors is a layout-change alarm."""
    alarms = [
        f"no meetings found for active body {b}"
        for b, n in sorted(meetings_per_active_body.items())
        if n == 0
    ]
    if fetched and parse_errors / fetched > PARSE_ERROR_ALARM_RATIO:
        alarms.append(f"parse errors {parse_errors}/{fetched} exceed {PARSE_ERROR_ALARM_RATIO:.0%}")
    return alarms
