"""CaseM / CloudNC at tampere.cloudnc.fi, PLAN.md §7.3"""

from __future__ import annotations

import datetime as dt
import logging

from ..bodies import guess_kind, is_included
from ..http import FetchFailed, NotFound, PoliteClient
from ..ids import item_id, meeting_id, slugify
from ..models import (
    AgendaItem,
    Attendance,
    Body,
    CityId,
    ItemRef,
    Meeting,
    MeetingRef,
    PersonRef,
    Speech,
    Stage,
    VoteEvent,
)
from ..parsers import casem as cp
from ..parsers import votes_casem as votes
from ..text import content_sha256, strip_pii

log = logging.getLogger(__name__)


class CasemAdapter:
    city = "tampere"
    has_attendance = True

    def __init__(self, client: PoliteClient, base_url: str = cp.BASE) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self._item_refs: dict[str, list[ItemRef]] = {}
        self._listing: dict[str, cp.ListingRow] = {}

    def _get(self, path_or_url: str) -> str:
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        resp = self.client.get(url)
        if resp.status in (404, 410):
            raise NotFound(url)
        if resp.status >= 400:
            raise FetchFailed(f"{url}: HTTP {resp.status}")
        return resp.text

    # -- bodies -------------------------------------------------------------------------------

    def discover_bodies(self) -> list[Body]:
        found = cp.parse_bodies(self._get("/fi-FI/Toimielimet"))
        bodies = []
        for site_slug, printed in found.items():
            name = cp.body_name(printed)
            slug = slugify(name)
            bodies.append(
                Body(
                    id=f"{self.city}/{slug}",
                    city=CityId.tampere,
                    name_fi=name,
                    kind=guess_kind(name),
                    source_ids={"slug": site_slug},
                    included=is_included(self.city, slug, name),
                )
            )
        return sorted(bodies, key=lambda b: b.id)

    # -- meetings -------------------------------------------------------------------------------

    def list_meetings(self, body: Body, since: dt.date, until: dt.date | None) -> list[MeetingRef]:
        rows = cp.parse_meetings(self._get(f"/fi-FI/Toimielimet/{body.source_ids['slug']}"))
        kept = sorted(
            (r for r in rows if r.date >= since and (until is None or r.date <= until)),
            key=lambda r: (r.date, r.meeting_key),
        )
        refs: list[MeetingRef] = []
        per_day: dict[dt.date, int] = {}
        for r in kept:
            per_day[r.date] = per_day.get(r.date, 0) + 1
            self._listing[r.url] = r
            refs.append(
                MeetingRef(
                    body_id=body.id,
                    date=r.date,
                    stage=r.stage,
                    source_url=r.url,
                    source_ids={"meeting": r.meeting_key},
                    same_day_index=per_day[r.date],
                )
            )
        return refs

    def fetch_meeting(self, ref: MeetingRef) -> Meeting:
        page = cp.parse_meeting(self._get(ref.source_url))
        mid = meeting_id(ref.body_id, ref.date, ref.same_day_index)
        if page.date and page.date != ref.date:
            log.warning("%s: page date %s differs from listing date", mid, page.date)
        stage = Stage.minutes if Stage.minutes in (ref.stage, page.stage) else ref.stage
        listing = self._listing.get(ref.source_url)
        self._item_refs[mid] = [
            ItemRef(
                meeting_id=mid,
                ordinal=r.ordinal,
                source_url=r.url,
                source_ids={"item": r.item_key},
                stage=stage,
                title=r.title,
                pykala=r.pykala if stage == Stage.minutes else None,
            )
            for r in page.rows
        ]
        attendance = (
            [
                Attendance(person_ref=PersonRef(raw=p.name), role_text=p.role, present=p.present, note=p.note)
                for p in page.participants
            ]
            if stage == Stage.minutes
            else []
        )
        source_ids = dict(ref.source_ids)
        if page.minutes_pdf:
            source_ids["pdf"] = page.minutes_pdf
        return Meeting(
            id=mid,
            body_id=ref.body_id,
            date=ref.date,
            start_time=listing.start_time if listing else None,
            end_time=None,
            location=listing.location if listing else None,
            stage=stage,
            source_url=ref.source_url,
            source_ids=source_ids,
            minutes_pdf_url=page.minutes_pdf if stage == Stage.minutes else None,
            attendance=attendance,
            items=[item_id(mid, r.ordinal) for r in page.rows],
        )

    def item_refs(self, meeting: Meeting) -> list[ItemRef]:
        return list(self._item_refs.get(meeting.id, []))

    # -- items ----------------------------------------------------------------------------------

    def fetch_item(self, ref: ItemRef) -> AgendaItem:
        return build_item(ref, cp.parse_item(self._get(ref.source_url)))

    def fetch_votes(self, item: AgendaItem) -> list[VoteEvent]:
        return item.votes  # parsed with the item

    def fetch_speeches(self, meeting: Meeting) -> list[Speech]:
        return []  # Tampere publishes no transcripts (§7.3)


def build_item(ref: ItemRef, page: cp.ItemPage) -> AgendaItem:
    final = ref.stage == Stage.minutes  # motions and votes only count once minutes are out (§6)
    motions, drafts = votes.parse_motions(page.deliberation_lines) if final else ([], [])
    item_votes = (
        votes.build_votes(
            page.votes_html, drafts, ref.source_url, votes.parse_results(page.deliberation_lines)
        )
        if final and page.votes_html
        else []
    )
    for m in motions:
        m.text = strip_pii(m.text)
    title = page.title or ref.title or ""  # the page marks confidential items, the listing does not
    sections = [s for s in page.sections if s.type not in ("statement", "dissent")]
    statements = [s for s in page.sections if s.type in ("statement", "dissent")]
    sha = content_sha256(title, *(s.text for s in page.sections), *(m.text for m in motions))
    source_ids = dict(ref.source_ids)
    if page.item_pdf:
        source_ids["pdf"] = page.item_pdf
    return AgendaItem(
        id=item_id(ref.meeting_id, ref.ordinal),
        meeting_id=ref.meeting_id,
        ordinal=ref.ordinal,
        pykala=ref.pykala if ref.pykala is not None else (page.pykala if final else None),
        title=title,
        case_number=page.case_number,
        presenter=page.presenter,
        preparers=page.preparers,
        sections=sections,
        motions=motions,
        votes=item_votes,
        statements=statements,
        attachments=page.attachments,
        source_url=ref.source_url,
        source_ids=source_ids,
        content_sha256=sha,
    )
