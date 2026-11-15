"""paatokset.turku.fi, read through its public JSON API (PLAN.md §7.6)."""

from __future__ import annotations

import datetime as dt
import json
import logging

from ..bodies import guess_kind, is_included
from ..http import FetchFailed, NotFound, PoliteClient, RobotsDisallowed
from ..ids import item_id, meeting_id, slugify
from ..models import (
    AgendaItem,
    Attendance,
    Ballot,
    Body,
    ItemRef,
    Meeting,
    MeetingRef,
    Outcome,
    PersonRef,
    SectionType,
    Speech,
    Stage,
    VoteEvent,
    VoteSource,
)
from ..parsers import turku as tp
from ..parsers import votes_cloudmeeting as votes
from ..parsers import votes_prose
from ..text import content_sha256, is_confidential, strip_pii
from .base import TransientItemError

log = logging.getLogger(__name__)


class TurkuAdapter:
    city = "turku"
    has_attendance = True

    def __init__(self, client: PoliteClient, base_url: str = tp.BASE) -> None:
        self.client = client
        # ah.turku.fi (the old archive) now redirects every path to paatokset.turku.fi.
        self.base_url = base_url.rstrip("/")
        self._item_refs: dict[str, list[ItemRef]] = {}
        self._items: dict[str, tp.ItemRow] = {}  # item api id → row from its meeting's call
        self._body_abbr: dict[str, str] = {}  # body id → lyhenne

    def _fetch(self, url: str):
        resp = self.client.get(url)
        if resp.status in (404, 410):
            raise NotFound(url)
        if resp.status >= 400:
            raise FetchFailed(f"{url}: HTTP {resp.status}")
        return resp

    def _api(self, path: str):
        url = f"{self.base_url}{tp.API}{path}"
        try:
            return json.loads(self._fetch(url).text)
        except json.JSONDecodeError as exc:
            raise FetchFailed(f"{url}: not JSON") from exc

    # -- bodies -------------------------------------------------------------------------------

    def discover_bodies(self) -> list[Body]:
        bodies = []
        for r in tp.parse_bodies(self._api("/toimielimet")):
            slug = slugify(r.name)
            bodies.append(
                Body(
                    id=f"{self.city}/{slug}",
                    city=self.city,
                    name_fi=r.name,
                    kind=guess_kind(r.name),
                    source_ids={"abbr": r.abbr, "route": tp.route_slug(r.name)},
                    active_to=r.active_to,
                    included=is_included(self.city, slug, r.name),
                )
            )
        return sorted(bodies, key=lambda b: b.id)

    def _abbr(self, body: Body) -> str:
        return body.source_ids["abbr"]

    # -- meetings -------------------------------------------------------------------------------

    def list_meetings(self, body: Body, since: dt.date, until: dt.date | None) -> list[MeetingRef]:
        abbr = self._abbr(body)
        self._body_abbr[body.id] = abbr
        route = body.source_ids.get("route") or tp.route_slug(body.name_fi)
        years = sorted(int(y) for y in self._api(f"/toimielin/{abbr}/paatosvuodet") or [] if str(y).isdigit())
        rows: list[tp.MeetingRow] = []
        for year in years:
            if year < since.year or (until is not None and year > until.year):
                continue
            rows.extend(tp.parse_meetings(self._api(f"/toimielin/{abbr}?vuosi={year}")))
        kept = sorted(
            (r for r in rows if r.date >= since and (until is None or r.date <= until)),
            key=lambda r: (r.date, len(r.api_id), r.api_id),
        )
        # Minutes replace the agenda of the same day.
        minutes_days = {r.date for r in kept if r.stage == Stage.minutes}
        kept = [r for r in kept if r.stage == Stage.minutes or r.date not in minutes_days]
        refs: list[MeetingRef] = []
        per_day: dict[dt.date, int] = {}
        for r in kept:
            per_day[r.date] = per_day.get(r.date, 0) + 1
            ids = {"meeting_id": r.api_id, "abbr": abbr, "route": route}
            if r.number:
                ids["number"] = r.number
            refs.append(
                MeetingRef(
                    body_id=body.id,
                    date=r.date,
                    stage=r.stage,
                    source_url=f"{self.base_url}/{route}/{r.api_id}",
                    source_ids=ids,
                    same_day_index=per_day[r.date],
                )
            )
        return refs

    def fetch_meeting(self, ref: MeetingRef) -> Meeting:
        api_id = ref.source_ids["meeting_id"]
        abbr = ref.source_ids.get("abbr") or self._body_abbr.get(ref.body_id, "")
        page = tp.parse_meeting(self._api(f"/poytakirja/{api_id}"))
        mid = meeting_id(ref.body_id, ref.date, ref.same_day_index)
        stage = Stage.minutes if Stage.minutes in (ref.stage, page.stage) else ref.stage
        refs = []
        for ordinal, row in enumerate(page.items, start=1):
            self._items[row.api_id] = row
            refs.append(
                ItemRef(
                    meeting_id=mid,
                    ordinal=ordinal,
                    source_url=f"{ref.source_url}/{row.api_id}",
                    source_ids={"item_id": row.api_id, "abbr": abbr}
                    | ({"agenda_no": row.agenda_no} if row.agenda_no else {}),
                    stage=stage,
                    title=row.title,
                    pykala=row.pykala if stage == Stage.minutes else None,
                )
            )
        self._item_refs[mid] = refs
        attendance = []
        if stage == Stage.minutes:
            try:
                people = tp.parse_attendance(self._api(f"/lasnaolotiedot/{api_id}"))
            except NotFound:
                people = []
            attendance = [
                Attendance(person_ref=PersonRef(raw=p.name), role_text=p.role, present=True) for p in people
            ]
        return Meeting(
            id=mid,
            body_id=ref.body_id,
            date=ref.date,
            start_time=page.start_time,
            end_time=page.end_time if stage == Stage.minutes else None,
            location=page.location,
            stage=stage,
            source_url=ref.source_url,
            source_ids=dict(ref.source_ids),
            attendance=attendance,
            items=[item_id(mid, r.ordinal) for r in refs],
        )

    def item_refs(self, meeting: Meeting) -> list[ItemRef]:
        return list(self._item_refs.get(meeting.id, []))

    # -- items ----------------------------------------------------------------------------------

    def _row(self, ref: ItemRef) -> tp.ItemRow:
        api_id = ref.source_ids["item_id"]
        row = self._items.get(api_id)
        if row is None:
            # The item came from an earlier run's refs: re-read its meeting (one call).
            meeting_api = ref.source_url.rstrip("/").split("/")[-2]
            for r in tp.parse_meeting(self._api(f"/poytakirja/{meeting_api}")).items:
                self._items[r.api_id] = r
            row = self._items.get(api_id)
        if row is None:
            raise NotFound(ref.source_url)
        return row

    def fetch_item(self, ref: ItemRef) -> AgendaItem:
        row = self._row(ref)
        abbr = ref.source_ids.get("abbr", "")
        final = ref.stage == Stage.minutes
        pykala = ref.pykala if ref.pykala is not None else (row.pykala if final else None)
        page = tp.parse_item(row.html, abbr, pykala)
        attachments = []
        if "liiteoheis" in row.html:
            try:
                attachments = tp.parse_attachments(self._api(f"/liitteet/{row.api_id}"), abbr, pykala)
            except NotFound:
                attachments = []
        motions = votes.parse_motions(page.own_lines) if final else []
        for m in motions:
            m.text = strip_pii(m.text)
        title = ref.title or row.title
        sections = [s for s in page.sections if s.type not in (SectionType.statement, SectionType.dissent)]
        statements = [s for s in page.sections if s.type in (SectionType.statement, SectionType.dissent)]
        sha = content_sha256(title, *(s.text for s in page.sections), *(m.text for m in motions))
        if final and not sections and not (row.confidential or is_confidential(title)) and row.html.strip():
            raise TransientItemError(ref.source_url)
        item = AgendaItem(
            id=item_id(ref.meeting_id, ref.ordinal),
            meeting_id=ref.meeting_id,
            ordinal=ref.ordinal,
            pykala=pykala,
            title=title,
            case_number=row.case_number,
            sections=sections,
            motions=motions,
            statements=statements,
            attachments=attachments,
            source_url=ref.source_url,
            source_ids=dict(ref.source_ids),
            content_sha256=sha,
        )
        if final:
            item.votes = self._votes(ref, row, page, item)
            resolve_outcomes(item.motions, item.votes)
        return item

    def _votes(self, ref: ItemRef, row: tp.ItemRow, page: tp.ItemPage, item: AgendaItem) -> list[VoteEvent]:
        prose = tp.parse_prose(page.own_lines)
        lists = [a for a in item.attachments if tp.VOTE_LIST_TITLE.search(a.title)]
        if not lists and not prose:
            # Committees and the board word votes their own way ("äänin 12-2", names in the text).
            return votes_prose.parse(page.own_lines, item_url=ref.source_url)
        pdf_votes: list[tp.TurkuPdfVote] = []
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
            parsed = tp.parse_vote_pdf(data)
            # One PDF can hold the meeting's other items' votes too; "Asia" is the agenda number.
            pdf_votes.extend(v for v in parsed if v.agenda_no is None or v.agenda_no == row.agenda_no)
        events = votes.build_votes(
            prose,
            pdf_votes,
            item_url=ref.source_url,
            pdf_url=lists[0].url if len(lists) == 1 else None,
            pdf_problem=problem,
        )
        # Party per voter, as the list prints it.
        by_order = list(pdf_votes)
        for ev in events:
            if ev.source != VoteSource.pdf:
                continue
            _drop_unlisted_absentees(ev)
            src = next((v for v in by_order if _same(v, ev)), None)
            if src is None:
                continue
            by_order.remove(src)
            ev.ballots = [
                Ballot(person_ref=b.person_ref, choice=b.choice, group_text=src.groups.get(b.person_ref.raw))
                for b in ev.ballots
            ]
        return events

    def fetch_votes(self, item: AgendaItem) -> list[VoteEvent]:
        return item.votes  # fetched with the item

    def fetch_speeches(self, meeting: Meeting) -> list[Speech]:
        return []  # Turku publishes no transcripts (meetings are on video at kepit.tv)


def _drop_unlisted_absentees(ev: VoteEvent) -> None:
    """Turku's lists count absent members ("Poissa / Frånvarande 1") but do not name them, so a
    missing absentee name is not a problem with the list."""
    if not ev.review_reason or any(b.choice == "poissa" for b in ev.ballots):
        return
    reasons = [r for r in ev.review_reason.split("; ") if not r.startswith("poissa: 0 names vs")]
    ev.review_reason = "; ".join(reasons) or None
    ev.needs_review = bool(reasons)


def _same(v: tp.TurkuPdfVote, ev: VoteEvent) -> bool:
    return [n for n, _ in v.ballots] == [b.person_ref.raw for b in ev.ballots] and v.jaa_label == ev.jaa_label


def resolve_outcomes(motions, events: list[VoteEvent]) -> None:
    """Turku's vote lists name the motion's proposer on its side ("Ei / Nej Muutos / Ändring Diop
    Paco"): the side that won decides the motion. Motions left open fall back to the shared rules."""
    used: set[int] = set()
    for mo in motions:
        surname = mo.proposer_ref.raw.split()[0] if mo.proposer_ref.raw else ""
        if mo.outcome is not None or not surname:
            continue
        for i, v in enumerate(events):
            if i in used or v.counts.jaa == v.counts.ei:
                continue
            on_ei, on_jaa = surname in v.ei_label.split(), surname in v.jaa_label.split()
            if on_ei == on_jaa:
                continue
            won = (v.counts.jaa > v.counts.ei) == on_jaa
            mo.outcome = Outcome.adopted if won else Outcome.rejected
            used.add(i)
            break
    votes.resolve_outcomes(motions, events)
