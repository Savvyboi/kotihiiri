"""Crawl orchestration shared by all adapters (PLAN.md §11, §12).

One run: discover bodies → list meetings since `since` → (re)fetch the meetings that need it →
write one deterministic JSON file per meeting. Which meetings are fetched:

- meetings not on disk yet;
- meetings on disk that are not at `minutes` stage yet (agenda → minutes);
- meetings dated inside the rolling window (`window_weeks`), to pick up corrections;
- meetings with an item recorded in `needs_refetch` by an earlier run;
- everything, with `revalidate` (conditional GETs keep that cheap).

Volatile run facts stay out of the meeting files. `data/state/{city}.json` holds only what the
next run needs (items to refetch, missing-item counters), so a no-change run leaves no diff.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import jsonio
from .adapters.base import Adapter, TransientItemError
from .bodies import default_included
from .config import CONFIG_DIR, DATA_DIR
from .http import FetchFailed, NotFound, RobotsDisallowed
from .ids import meeting_file_path, meeting_id
from .models import AgendaItem, Body, ItemRef, ItemStatus, Meeting, MeetingFile, MeetingRef, Stage
from .text import content_sha256
from .validate import layout_alarm

log = logging.getLogger(__name__)

MISSING_BEFORE_TOMBSTONE = 2


@dataclass
class CrawlReport:
    city: str
    bodies: int = 0
    meetings_listed: int = 0
    meetings_fetched: int = 0
    meetings_skipped: int = 0
    items_fetched: int = 0
    parse_errors: int = 0
    needs_refetch: list[str] = field(default_factory=list)
    tombstoned: list[str] = field(default_factory=list)
    files_changed: int = 0
    stopped_early: bool = False
    alarms: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.city}: bodies={self.bodies} listed={self.meetings_listed} "
            f"fetched={self.meetings_fetched} "
            f"skipped={self.meetings_skipped} items={self.items_fetched} parse_errors={self.parse_errors} "
            f"needs_refetch={len(self.needs_refetch)} tombstoned={len(self.tombstoned)} "
            f"files_changed={self.files_changed}" + (" STOPPED_EARLY" if self.stopped_early else "")
        )


# -- bodies -------------------------------------------------------------------------------

_BODIES_HEADER = """\
# Written by `kunta discover` / `kunta crawl`. Add `included: true|false` to a body to override the
# default exclude rules (kunta/bodies.py); manual keys survive re-discovery. `excluded_by_rule`
# is informational.
"""


def write_bodies(
    city: str, bodies: list[Body], config_dir: Path = CONFIG_DIR, data_dir: Path = DATA_DIR
) -> None:
    path = config_dir / "bodies" / f"{city}.yaml"
    existing = {}
    if path.exists():
        existing = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("bodies") or {}
    merged: dict[str, dict] = {}
    for b in bodies:
        slug = b.id.split("/", 1)[1]
        entry = dict(existing.get(slug) or {})
        entry["name_fi"] = b.name_fi
        entry["kind"] = str(b.kind)
        if default_included(b.name_fi):
            entry.pop("excluded_by_rule", None)
        else:
            entry["excluded_by_rule"] = True
        merged[slug] = entry
    for slug, entry in existing.items():  # keep bodies a human added by hand
        merged.setdefault(slug, entry)
    text = _BODIES_HEADER + yaml.safe_dump(
        {"bodies": dict(sorted(merged.items()))}, allow_unicode=True, sort_keys=True, width=110
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    jsonio.write(data_dir / city / "bodies.json", sorted(bodies, key=lambda b: b.id))


# -- state --------------------------------------------------------------------------------


def _state_path(city: str, data_dir: Path) -> Path:
    return data_dir / "state" / f"{city}.json"


def load_state(city: str, data_dir: Path = DATA_DIR) -> dict:
    p = _state_path(city, data_dir)
    state = jsonio.read(p) if p.exists() else {}
    state.setdefault("needs_refetch", [])
    state.setdefault("missing", {})
    return state


# -- crawl --------------------------------------------------------------------------------


def _placeholder(ref: ItemRef) -> AgendaItem:
    title = ref.title or ""
    return AgendaItem(
        id=f"{ref.meeting_id}/{ref.ordinal}",
        meeting_id=ref.meeting_id,
        ordinal=ref.ordinal,
        pykala=ref.pykala,
        title=title,
        source_url=ref.source_url,
        source_ids=dict(ref.source_ids),
        content_sha256=content_sha256(title),
    )


def _tombstone(item: AgendaItem) -> AgendaItem:
    return item.model_copy(
        update={
            "status": ItemStatus.tombstone,
            "sections": [],
            "motions": [],
            "votes": [],
            "statements": [],
            "disqualified": [],
            "attachments": [],
            "decision_summary": None,
            "content_sha256": content_sha256(item.title),
        }
    )


def needs_fetch(
    ref: MeetingRef,
    path: Path,
    *,
    today: dt.date,
    window_weeks: int | None,
    revalidate: bool,
    refetch_meetings: set[str],
    mid: str,
) -> bool:
    if revalidate or window_weeks is None or not path.exists() or mid in refetch_meetings:
        return True
    if jsonio.read(path)["meeting"].get("stage") != Stage.minutes.value:
        return True  # agenda → decisions → minutes
    return ref.date >= today - dt.timedelta(weeks=window_weeks)


def crawl(
    adapter: Adapter,
    city: str,
    *,
    since: dt.date,
    until: dt.date | None = None,
    body_filter: str | None = None,
    window_weeks: int | None = None,
    revalidate: bool = False,
    today: dt.date | None = None,
    max_seconds: float | None = None,
    data_dir: Path = DATA_DIR,
    config_dir: Path = CONFIG_DIR,
) -> CrawlReport:
    started = time.monotonic()
    today = today or dt.date.today()
    report = CrawlReport(city)

    bodies = adapter.discover_bodies()
    write_bodies(city, bodies, config_dir, data_dir)
    active = [
        b for b in bodies if b.included and (body_filter is None or b.id.split("/", 1)[1] == body_filter)
    ]
    report.bodies = len(active)

    state = load_state(city, data_dir)
    refetch_items: set[str] = set(state["needs_refetch"])
    refetch_meetings = {i.rsplit("/", 1)[0] for i in refetch_items}
    missing: dict[str, int] = dict(state["missing"])
    still_refetch: set[str] = set()

    per_body: dict[str, int] = {}
    retry_queue: list[tuple[Path, Meeting, ItemRef]] = []
    written: dict[Path, MeetingFile] = {}

    def out_of_time() -> bool:
        return max_seconds is not None and time.monotonic() - started > max_seconds

    for body in active:
        if out_of_time():
            report.stopped_early = True
            break
        try:
            refs = adapter.list_meetings(body, since, until)
        except (FetchFailed, RobotsDisallowed) as exc:
            log.error("%s: listing failed: %s", body.id, exc)
            report.parse_errors += 1
            continue
        per_body[body.id] = len(refs)
        report.meetings_listed += len(refs)

        for ref in refs:
            if out_of_time():
                report.stopped_early = True
                break
            mid = meeting_id(ref.body_id, ref.date, ref.same_day_index)
            path = data_dir / meeting_file_path(mid)
            if not needs_fetch(
                ref,
                path,
                today=today,
                window_weeks=window_weeks,
                revalidate=revalidate,
                refetch_meetings=refetch_meetings,
                mid=mid,
            ):
                report.meetings_skipped += 1
                continue
            try:
                meeting = adapter.fetch_meeting(ref)
            except (FetchFailed, RobotsDisallowed) as exc:
                log.error("%s: meeting fetch failed: %s", mid, exc)
                report.parse_errors += 1
                continue
            report.meetings_fetched += 1
            old = (
                {i["id"]: AgendaItem.model_validate(i) for i in jsonio.read(path)["items"]}
                if path.exists()
                else {}
            )
            items: list[AgendaItem] = []
            for iref in adapter.item_refs(meeting):
                iid = f"{mid}/{iref.ordinal}"
                try:
                    item = adapter.fetch_item(iref)
                    report.items_fetched += 1
                    missing.pop(iid, None)
                except NotFound:
                    missing[iid] = missing.get(iid, 0) + 1
                    prev = old.get(iid)
                    if prev is not None and missing[iid] >= MISSING_BEFORE_TOMBSTONE:
                        item = _tombstone(prev)
                        report.tombstoned.append(iid)
                    else:
                        item = prev or _placeholder(iref)
                        still_refetch.add(iid)
                except Exception as exc:  # transient load error, network failure or parser bug
                    if isinstance(exc, TransientItemError):
                        retry_queue.append((path, meeting, iref))
                    else:
                        log.error("%s: item failed: %s: %s", iid, type(exc).__name__, exc)
                        report.parse_errors += 1
                        still_refetch.add(iid)
                    item = old.get(iid) or _placeholder(iref)
                items.append(item)
            mf = MeetingFile(meeting=meeting, items=items)
            written[path] = mf
            report.files_changed += jsonio.write(path, mf)

    # "Virhe päätöstä ladattaessa" is transient: one more try later in the run, then needs_refetch.
    for path, meeting, iref in retry_queue:
        iid = f"{meeting.id}/{iref.ordinal}"
        try:
            item = adapter.fetch_item(iref)
            report.items_fetched += 1
        except Exception as exc:
            log.warning("%s: still failing (%s); marked needs_refetch", iid, type(exc).__name__)
            still_refetch.add(iid)
            continue
        mf = written[path]
        mf.items = [item if i.id == iid else i for i in mf.items]
        report.files_changed += jsonio.write(path, mf)

    # Items we did not get to this run stay queued.
    done_meetings = {mf.meeting.id for mf in written.values()}
    still_refetch |= {i for i in refetch_items if i.rsplit("/", 1)[0] not in done_meetings}
    report.needs_refetch = sorted(still_refetch)
    jsonio.write(
        _state_path(city, data_dir),
        {"needs_refetch": report.needs_refetch, "missing": dict(sorted(missing.items()))},
    )

    # Layout-change alarm: a body that has data on disk but lists nothing, or >5 % parse errors.
    with_data = {
        b.id: per_body.get(b.id, 0)
        for b in active
        if b.id in per_body and any((data_dir / city / "meetings").glob(f"*/{b.id.split('/', 1)[1]}--*.json"))
    }
    report.alarms = layout_alarm(with_data, report.items_fetched + report.parse_errors, report.parse_errors)
    return report
