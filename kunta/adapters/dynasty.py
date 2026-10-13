"""Dynasty at espoo.oncloudos.com, PLAN.md §7.2"""

from __future__ import annotations

import datetime as dt
import logging

from ..bodies import guess_kind, is_included
from ..http import FetchFailed, NotFound, PoliteClient, RobotsDisallowed
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
from ..parsers import dynasty as dp
from ..parsers import votes_cloudmeeting as votes
from ..text import content_sha256, strip_pii
from .base import TransientItemError

log = logging.getLogger(__name__)

PATH = "/cgi/DREQUEST.PHP"


class DynastyAdapter:
    city = "espoo"
    has_attendance = True

    def __init__(self, client: PoliteClient, base_url: str = dp.BASE) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self._item_refs: dict[str, list[ItemRef]] = {}

    def _fetch(self, path_or_url: str):
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        resp = self.client.get(url)
        if resp.status in (404, 410):
            raise NotFound(url)
        if resp.status >= 400:
            raise FetchFailed(f"{url}: HTTP {resp.status}")
        return resp

    def _get(self, path_or_url: str) -> str:
        resp = self._fetch(path_or_url)
        ct = resp.content_type.lower()
        declared = ct.split("charset=", 1)[1].split(";")[0].strip(" \"'") if "charset=" in ct else None
        return dp.decode(resp.content, declared)

    # -- bodies -------------------------------------------------------------------------------

    def discover_bodies(self) -> list[Body]:
        found = dp.parse_bodies(self._get(f"{PATH}?page=meeting_frames"))
        bodies = []
        for dyn_id, name in found.items():
            slug = slugify(name)
            bodies.append(
                Body(
                    id=f"{self.city}/{slug}",
                    city=CityId.espoo,
                    name_fi=name,
                    kind=guess_kind(name),
                    source_ids={"dynasty_id": dyn_id},
                    included=is_included(self.city, slug, name),
                )
            )
        return sorted(bodies, key=lambda b: b.id)

    # -- meetings -------------------------------------------------------------------------------

    def list_meetings(self, body: Body, since: dt.date, until: dt.date | None) -> list[MeetingRef]:
        dyn_id = body.source_ids["dynasty_id"]
        rows = dp.parse_meetings(self._get(f"{PATH}?page=meetings&id={dyn_id}"))
        kept = sorted(
            (r for r in rows if r.date >= since and (until is None or r.date <= until)),
            key=lambda r: (r.date, len(r.meeting_id), r.meeting_id),
        )
        refs: list[MeetingRef] = []
        per_day: dict[dt.date, int] = {}
        for r in kept:
            per_day[r.date] = per_day.get(r.date, 0) + 1
            refs.append(
                MeetingRef(
                    body_id=body.id,
                    date=r.date,
                    stage=r.stage,
                    source_url=f"{self.base_url}{PATH}?page=meeting&id={r.meeting_id}",
                    source_ids={"meeting_id": r.meeting_id},
                    same_day_index=per_day[r.date],
                )
            )
        return refs

    def fetch_meeting(self, ref: MeetingRef) -> Meeting:
        dyn_mid = ref.source_ids["meeting_id"]
        page = dp.parse_meeting(self._get(ref.source_url), dyn_mid)
        mid = meeting_id(ref.body_id, ref.date, ref.same_day_index)
        if page.date and page.date != ref.date:
            log.warning("%s: page date %s differs from listing date", mid, page.date)
        # The listing label leads; the page heading can lag behind it (§7.2). Either saying
        # "Pöytäkirja" means the minutes are out.
        stage = Stage.minutes if Stage.minutes in (ref.stage, page.stage) else ref.stage
        self._item_refs[mid] = [
            ItemRef(
                meeting_id=mid,
                ordinal=r.ordinal,
                source_url=r.url,
                source_ids={"item_id": f"{dyn_mid}-{r.ordinal}"},
                stage=stage,
                title=r.title,
                pykala=r.pykala if stage == Stage.minutes else None,
            )
            for r in page.rows
        ]
        attendance = (
            [
                Attendance(person_ref=PersonRef(raw=p.name), role_text=p.role, present=True)
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
            start_time=page.start_time,
            end_time=page.end_time,
            location=page.location,
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
        page = dp.parse_item(self._get(ref.source_url))
        item = build_item(ref, page)
        if ref.stage == Stage.minutes and votes.mentions_vote_list(page.deliberation_lines):
            item.votes = self._votes(ref, page, item)
            votes.resolve_outcomes(item.motions, item.votes)
        return item

    def _votes(self, ref: ItemRef, page: dp.ItemPage, item: AgendaItem) -> list[VoteEvent]:
        prose = votes.parse_prose(page.deliberation_lines)
        lists = [a for a in item.attachments if votes.VOTE_LIST_TITLE.search(a.title)]
        pykala = item.pykala
        pdf_votes: list[votes.PdfVote] = []
        problem = None if lists else "no vote list attached; counts from the minutes text"
        for att in lists:
            try:
                data = self._fetch(att.url).content
            except NotFound:
                problem = "vote list PDF not found; counts from the minutes text"
                continue
            except RobotsDisallowed:
                problem = "vote list PDF disallowed by robots.txt; counts from the minutes text"
                continue
            except FetchFailed as exc:
                raise TransientItemError(f"{ref.source_url}: vote list: {exc}") from exc
            parsed = votes.parse_vote_pdf(data)
            # A list printed for another § (an earlier body's vote) is not this item's.
            pdf_votes.extend(v for v in parsed if v.pykala is None or pykala is None or v.pykala == pykala)
        return votes.build_votes(
            prose,
            pdf_votes,
            item_url=ref.source_url,
            pdf_url=lists[0].url if len(lists) == 1 else None,
            pdf_problem=problem,
        )

    def fetch_votes(self, item: AgendaItem) -> list[VoteEvent]:
        return item.votes  # fetched with the item

    def fetch_speeches(self, meeting: Meeting) -> list[Speech]:
        return []  # Espoo publishes no transcripts (§7.2)


def build_item(ref: ItemRef, page: dp.ItemPage) -> AgendaItem:
    final = ref.stage == Stage.minutes  # motions and votes only count once minutes are out (§6)
    motions = votes.parse_motions(page.deliberation_lines) if final else []
    for m in motions:
        m.text = strip_pii(m.text)
    title = ref.title or page.title or ""
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
        statements=statements,
        attachments=page.attachments,
        source_url=ref.source_url,
        source_ids=source_ids,
        content_sha256=sha,
    )
