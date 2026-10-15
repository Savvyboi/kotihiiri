"""Triplan Tweb at paatokset.vantaa.fi, PLAN.md §7.4. Oulu runs the same software but stays
disabled (§2); `adapter_for` refuses it before any fetch."""

from __future__ import annotations

import datetime as dt
import logging

from ..bodies import guess_kind, is_included
from ..http import FetchFailed, NotFound, PoliteClient, RobotsDisallowed
from ..ids import item_id, meeting_id, slugify
from ..models import (
    AgendaItem,
    Attendance,
    Ballot,
    Body,
    Choice,
    ItemRef,
    Meeting,
    MeetingRef,
    PersonRef,
    Speech,
    Stage,
    VoteEvent,
)
from ..parsers import tweb as tp
from ..parsers import votes_cloudmeeting as votes
from ..pdf import pdf_pages
from ..text import content_sha256, strip_pii
from .base import TransientItemError

log = logging.getLogger(__name__)

MINUTES_LIST = "/ktwebbin/dbisa.dll/ktwebscr/pk_kokl_tweb.htm?+kirjaamo={id}"
AGENDA_LIST = "/ktwebscr/epj_kokl_tweb.htm?+kirjaamo={id}"
BODY_LIST = "/ktwebscr/pk_tek_tweb.htm"
DLL = "/ktwebbin/dbisa.dll"
COVER_PAGES = 6  # of the compiled minutes: the table of contents, then the cover page


class TwebAdapter:
    city = "vantaa"
    has_attendance = True

    def __init__(self, client: PoliteClient, base_url: str = tp.BASE) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self._item_refs: dict[str, list[ItemRef]] = {}
        self._dates: dict[str, dt.date] = {}
        self._att: dict[str, dict[int, str]] = {}  # meeting → ordinal → attachments page
        self._dll_only = False

    def configure(self, extra: dict) -> None:
        # Some self-hosted installs serve every script under /ktwebbin/dbisa.dll/ (§18.1).
        self._dll_only = bool(extra.get("tweb_dll_paths"))

    @property
    def _link_base(self) -> str:
        """What relative links on this host's pages resolve against (+ "/ktwebscr/")."""
        return self.base_url + DLL if self._dll_only else self.base_url

    def _path(self, path: str) -> str:
        return DLL + path if self._dll_only and not path.startswith(DLL) else path

    def _fetch(self, path_or_url: str):
        url = path_or_url if path_or_url.startswith("http") else self.base_url + self._path(path_or_url)
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
        return tp.decode(resp.content, declared)

    def _doc_lines(self, url: str, max_pages: int | None = None) -> list[str]:
        """A `fileshow` document as text lines: most are PDFs, a few are served as HTML."""
        resp = self._fetch(url)
        if resp.content[:5] == b"%PDF-" or "pdf" in resp.content_type.lower():
            return [ln for page in pdf_pages(resp.content, max_pages) for ln in page]
        return tp.html_lines(tp.decode(resp.content))

    # -- bodies -------------------------------------------------------------------------------

    def discover_bodies(self) -> list[Body]:
        found = tp.parse_bodies(self._get(BODY_LIST))
        bodies = []
        for kirjaamo, name in found.items():
            slug = slugify(name)
            bodies.append(
                Body(
                    id=f"{self.city}/{slug}",
                    city=self.city,
                    name_fi=name,
                    kind=guess_kind(name),
                    source_ids={"kirjaamo": kirjaamo},
                    included=is_included(self.city, slug, name),
                )
            )
        return sorted(bodies, key=lambda b: b.id)

    # -- meetings -------------------------------------------------------------------------------

    def list_meetings(self, body: Body, since: dt.date, until: dt.date | None) -> list[MeetingRef]:
        kirjaamo = body.source_ids["kirjaamo"]
        minutes = tp.parse_meeting_list(self._get(MINUTES_LIST.format(id=kirjaamo)), self._link_base)
        agendas = tp.parse_meeting_list(self._get(AGENDA_LIST.format(id=kirjaamo)), self._link_base)
        # A meeting moves from the agenda list to the minutes list once the minutes are out.
        published = {(r.date, r.start_time) for r in minutes}
        rows = minutes + [r for r in agendas if (r.date, r.start_time) not in published]
        kept = sorted(
            (r for r in rows if r.date >= since and (until is None or r.date <= until)),
            key=lambda r: (r.date, r.start_time or "", r.bid),
        )
        refs: list[MeetingRef] = []
        per_day: dict[dt.date, int] = {}
        for r in kept:
            per_day[r.date] = per_day.get(r.date, 0) + 1
            refs.append(
                MeetingRef(
                    body_id=body.id,
                    date=r.date,
                    stage=Stage.minutes if r.minutes else Stage.agenda,
                    source_url=r.url,
                    source_ids={"bid": r.bid} | ({"time": r.start_time} if r.start_time else {}),
                    same_day_index=per_day[r.date],
                )
            )
        return refs

    def fetch_meeting(self, ref: MeetingRef) -> Meeting:
        page = tp.parse_meeting(self._get(ref.source_url), self._link_base)
        mid = meeting_id(ref.body_id, ref.date, ref.same_day_index)
        stage = Stage(ref.stage)
        self._dates[mid] = ref.date
        self._item_refs[mid] = [
            ItemRef(
                meeting_id=mid,
                ordinal=r.ordinal,
                source_url=r.url or ref.source_url,
                source_ids={"docid": r.docid} if r.docid else {},
                stage=stage,
                title=r.title,
                pykala=r.pykala if stage == Stage.minutes else None,
            )
            for r in page.rows
        ]
        self._att[mid] = {r.ordinal: r.attachments_url for r in page.rows if r.attachments_url}
        cover = tp.Cover()
        # Meetings before 2026 have no separate cover page; the compiled minutes open with it.
        cover_url, pages = (page.cover_pdf, None) if page.cover_pdf else (page.compiled_pdf, COVER_PAGES)
        if stage == Stage.minutes and cover_url:
            try:
                cover = tp.parse_cover(self._doc_lines(cover_url, pages))
            except (NotFound, RobotsDisallowed) as exc:
                log.warning("%s: cover page: %s", mid, exc)
        if cover.date and cover.date != ref.date:
            log.warning("%s: cover page date %s differs from the listing", mid, cover.date)
        source_ids = dict(ref.source_ids)
        if page.compiled_pdf:
            source_ids["pdf"] = page.compiled_pdf
        return Meeting(
            id=mid,
            body_id=ref.body_id,
            date=ref.date,
            start_time=cover.start_time or ref.source_ids.get("time"),
            end_time=cover.end_time,
            location=cover.location,
            stage=stage,
            source_url=ref.source_url,
            source_ids=source_ids,
            minutes_pdf_url=page.compiled_pdf if stage == Stage.minutes else None,
            attendance=[
                Attendance(person_ref=PersonRef(raw=p.name), role_text=p.role, present=p.present, note=p.note)
                for p in cover.participants
            ],
            items=[item_id(mid, r.ordinal) for r in page.rows],
        )

    def item_refs(self, meeting: Meeting) -> list[ItemRef]:
        return list(self._item_refs.get(meeting.id, []))

    # -- items ----------------------------------------------------------------------------------

    def fetch_item(self, ref: ItemRef) -> AgendaItem:
        if "docid" not in ref.source_ids:  # no document published (confidential)
            return build_item(ref, tp.ItemDoc(), [])
        lines = self._doc_lines(ref.source_url)
        doc = tp.parse_item_lines(lines, ref.title)
        tp.end_at_meeting(doc, self._meeting_date(ref), ref.pykala)
        attachments = []
        att_url = self._att.get(ref.meeting_id, {}).get(ref.ordinal)
        if att_url:
            try:
                attachments = tp.parse_attachments(self._get(att_url), self._link_base)
            except (NotFound, RobotsDisallowed) as exc:
                log.warning("%s: attachments: %s", ref.source_url, exc)
            except FetchFailed as exc:
                raise TransientItemError(f"{ref.source_url}: attachments: {exc}") from exc
        item = build_item(ref, doc, attachments)
        if ref.stage == Stage.minutes:
            item.votes = self._votes(ref, item, doc)
        return item

    def _votes(self, ref: ItemRef, item: AgendaItem, doc: tp.ItemDoc) -> list[VoteEvent]:
        _, _, deliberation = tp.item_sections(doc)
        prose = tp.parse_case(deliberation)[1]
        if not prose:
            return []
        reports = [a for a in item.attachments if votes.VOTE_LIST_TITLE.search(a.title)]
        date = self._meeting_date(ref)
        report_votes: list[tp.ReportVote] = []
        used: list[str] = []  # reports that hold this meeting's votes
        problem = None if reports else "no vote report attached; counts from the minutes text"
        for att in reports:
            try:
                parsed = tp.parse_vote_report(self._doc_lines(att.url))
            except NotFound:
                problem = "vote report not found; counts from the minutes text"
                continue
            except RobotsDisallowed:
                problem = "vote report disallowed by robots.txt; counts from the minutes text"
                continue
            except FetchFailed as exc:
                raise TransientItemError(f"{ref.source_url}: vote report: {exc}") from exc
            # An item's attachments also carry earlier bodies' reports ("Äänestysraportti KH …");
            # keep this meeting's votes (a late vote can run past midnight).
            mine = [
                v
                for v in parsed
                if (v.pykala is None or item.pykala is None or v.pykala == item.pykala)
                and (v.date is None or 0 <= (v.date - date).days <= 1)
            ]
            report_votes.extend(mine)
            if mine:
                used.append(att.url)
        events = votes.build_votes(
            prose,
            report_votes,
            item_url=ref.source_url,
            pdf_url=used[0] if len(used) == 1 else None,
            pdf_problem=problem,
        )
        by_sentence = {p.sentence: p for p in prose}
        groups = {name: g for v in report_votes for name, g in v.groups.items()}
        for ev in events:
            pv = by_sentence.get(ev.result_text or "")
            for b in ev.ballots:
                b.group_text = groups.get(b.person_ref.raw)
            if pv is None:
                continue
            ev.jaa_label = ev.jaa_label or pv.jaa_label
            ev.ei_label = ev.ei_label or pv.ei_label
            if not ev.ballots and pv.names:
                # Boards print the voters' surnames in the sentence: "13 jaa-ääntä (Karinen, …)".
                ev.ballots = [
                    Ballot(person_ref=PersonRef(raw=n), choice=c) for c, ns in pv.names.items() for n in ns
                ]
                named = {c: len(ns) for c, ns in pv.names.items()}
                if (
                    named.get(Choice.jaa, 0) == pv.a
                    and named.get(Choice.ei, 0) == pv.b
                    and (named.get(Choice.tyhja, 0) == pv.tyhja)
                ):
                    ev.needs_review, ev.review_reason = False, None
        return events

    def _meeting_date(self, ref: ItemRef) -> dt.date:
        return self._dates.get(ref.meeting_id) or dt.date.fromisoformat(ref.meeting_id.rsplit("/", 1)[1][:10])

    def fetch_votes(self, item: AgendaItem) -> list[VoteEvent]:
        return item.votes  # fetched with the item

    def fetch_speeches(self, meeting: Meeting) -> list[Speech]:
        return []  # transcript index unverified (§7.4 S4)


def build_item(ref: ItemRef, doc: tp.ItemDoc, attachments) -> AgendaItem:
    final = ref.stage == Stage.minutes  # motions and votes only count once minutes are out (§6)
    sections, statements, deliberation = tp.item_sections(doc)
    motions = tp.parse_motions(deliberation) if final else []
    for m in motions:
        m.text = strip_pii(m.text)
    title = ref.title or ""
    sha = content_sha256(title, *(s.text for s in sections + statements), *(m.text for m in motions))
    return AgendaItem(
        id=item_id(ref.meeting_id, ref.ordinal),
        meeting_id=ref.meeting_id,
        ordinal=ref.ordinal,
        pykala=ref.pykala if final else None,
        title=title,
        case_number=doc.case_number,
        sections=sections,
        motions=motions,
        statements=statements,
        attachments=attachments,
        source_url=ref.source_url,
        source_ids=dict(ref.source_ids),
        content_sha256=sha,
    )
