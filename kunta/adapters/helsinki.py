"""paatokset.hel.fi (Drupal front of Ahjo), PLAN.md §7.1"""

from __future__ import annotations

import datetime as dt
import logging

from ..bodies import guess_kind, is_included
from ..http import FetchFailed, NotFound, PoliteClient
from ..ids import item_id, meeting_id
from ..models import AgendaItem, Body, CityId, ItemRef, Meeting, MeetingRef, Speech, Stage, VoteEvent
from ..parsers import helsinki as hp
from ..parsers import votes_helsinki as votes
from ..text import content_sha256, strip_pii
from .base import TransientItemError

log = logging.getLogger(__name__)

SEED_SLUGS = [
    "kaupunginvaltuusto",
    "kaupunginhallitus",
    "kaupunginhallituksen-konsernijaosto",
    "kaupunginhallituksen-elinkeinojaosto",
]
COMMITTEES_PAGE = "/fi/paattajat/lautakunnat-ja-johtokunnat"
MAX_LISTING_PAGES = 60


class HelsinkiAdapter:
    city = "helsinki"
    # Meeting pages carry no participant list; attendance comes with the roster work in M5.
    has_attendance = False

    def __init__(self, client: PoliteClient, base_url: str = hp.BASE) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self._item_refs: dict[str, list[ItemRef]] = {}

    def _get(self, path_or_url: str) -> str:
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        resp = self.client.get(url)
        if resp.status in (404, 410):
            raise NotFound(url)
        if resp.status >= 400:
            raise FetchFailed(f"{url}: HTTP {resp.status}")
        return resp.text

    # -- bodies ---------------------------------------------------------------------------

    def discover_bodies(self) -> list[Body]:
        found = hp.parse_body_links(self._get(COMMITTEES_PAGE))
        for slug in SEED_SLUGS:
            if slug not in found:
                name = hp.parse_body_name(self._get(f"/fi/paattajat/{slug}"))
                if name:
                    found[slug] = name
        bodies = [
            Body(
                id=f"{self.city}/{slug}",
                city=CityId.helsinki,
                name_fi=name,
                kind=guess_kind(name),
                source_ids={"slug": slug},
                included=is_included(self.city, slug, name),
            )
            for slug, name in found.items()
        ]
        return sorted(bodies, key=lambda b: b.id)

    # -- meetings -------------------------------------------------------------------------

    def list_meetings(self, body: Body, since: dt.date, until: dt.date | None) -> list[MeetingRef]:
        slug = body.source_ids.get("slug") or body.id.split("/", 1)[1]
        rows: dict[str, hp.ListingRow] = {}
        for page in range(MAX_LISTING_PAGES):
            html = self._get(f"/fi/paattajat/{slug}/asiakirjat?page={page}")
            page_rows = hp.parse_listing(html, slug)
            new = [r for r in page_rows if r.code not in rows]
            if not new:
                break
            for r in new:
                rows[r.code] = r
            if min(r.date for r in new) < since:
                break  # the listing is newest first
        else:
            log.warning("%s: listing longer than %d pages", body.id, MAX_LISTING_PAGES)

        kept = sorted(
            (r for r in rows.values() if r.date >= since and (until is None or r.date <= until)),
            key=lambda r: (r.date, r.year, r.number, r.code),
        )
        refs: list[MeetingRef] = []
        per_day: dict[dt.date, int] = {}
        for r in kept:
            per_day[r.date] = per_day.get(r.date, 0) + 1
            refs.append(
                MeetingRef(
                    body_id=body.id,
                    date=r.date,
                    stage=Stage.minutes if r.label == "Pöytäkirja" else Stage.agenda,
                    source_url=r.url,
                    source_ids={"meeting_code": r.code, "number": f"{r.number}/{r.year}"},
                    same_day_index=per_day[r.date],
                )
            )
        return refs

    def fetch_meeting(self, ref: MeetingRef) -> Meeting:
        page = hp.parse_meeting(self._get(ref.source_url))
        mid = meeting_id(ref.body_id, ref.date, ref.same_day_index)
        if page.date and page.date != ref.date:
            log.warning("%s: page date %s differs from listing date", mid, page.date)
        source_ids = dict(ref.source_ids)
        if page.print_pdf:
            source_ids["print_pdf"] = page.print_pdf
        if page.transcript_pdf:
            source_ids["transcript_pdf"] = page.transcript_pdf
        self._item_refs[mid] = [
            ItemRef(
                meeting_id=mid,
                ordinal=r.ordinal,
                source_url=r.url,
                source_ids={"case": r.url.split("/fi/asia/", 1)[1].split("?", 1)[0]}
                | ({"decision": r.url.split("paatos=", 1)[1]} if "paatos=" in r.url else {}),
                stage=page.stage,
                title=r.title,
                pykala=r.pykala,
            )
            for r in page.rows
        ]
        return Meeting(
            id=mid,
            body_id=ref.body_id,
            date=ref.date,
            start_time=page.start_time,
            end_time=page.end_time,
            location=page.location,
            stage=page.stage,
            source_url=ref.source_url,
            source_ids=source_ids,
            minutes_pdf_url=page.print_pdf if page.stage == Stage.minutes else None,
            video_url=page.video_url,
            items=[item_id(mid, r.ordinal) for r in page.rows],
        )

    def item_refs(self, meeting: Meeting) -> list[ItemRef]:
        return list(self._item_refs.get(meeting.id, []))

    # -- items ----------------------------------------------------------------------------

    def fetch_item(self, ref: ItemRef) -> AgendaItem:
        html = self._get(ref.source_url)
        page = hp.parse_item(html)
        if ref.stage == Stage.minutes and not page.has_decision() and page.load_error:
            raise TransientItemError(ref.source_url)
        return build_item(ref, page)

    def fetch_votes(self, item: AgendaItem) -> list[VoteEvent]:
        return item.votes  # parsed inline from the item page

    def fetch_speeches(self, meeting: Meeting) -> list[Speech]:
        return []  # M6


def build_item(ref: ItemRef, page: hp.ItemPage) -> AgendaItem:
    final = ref.stage == Stage.minutes  # votes and motions only count once minutes are out (§6)
    item_votes = (
        votes.build_votes(
            votes.parse_text_votes(page.deliberation_lines),
            votes.parse_table_votes(page.vote_blocks),
            ref.source_url,
        )
        if final
        else []
    )
    motions = votes.parse_motions(page.deliberation_lines) if final else []
    for m in motions:
        m.text = strip_pii(m.text)
    votes.resolve_outcomes(motions, item_votes)
    title = ref.title or page.title or ""
    sections = [s for s in page.sections if s.type not in ("statement", "dissent")]
    statements = [s for s in page.sections if s.type in ("statement", "dissent")]
    sha = content_sha256(title, *(s.text for s in page.sections), *(m.text for m in motions))
    return AgendaItem(
        id=item_id(ref.meeting_id, ref.ordinal),
        meeting_id=ref.meeting_id,
        ordinal=ref.ordinal,
        pykala=ref.pykala if ref.pykala is not None else page.pykala,
        title=title,
        case_number=page.case_number,
        presenter=page.presenter,
        sections=sections,
        motions=motions,
        votes=item_votes,
        statements=statements,
        attachments=page.attachments,
        source_url=ref.source_url,
        source_ids=dict(ref.source_ids),
        content_sha256=sha,
    )
