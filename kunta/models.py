"""Pydantic v2 data models (PLAN.md §5). JSON on disk mirrors these models."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# Municipality slug from config/municipalities.yaml (PLAN.md §5.1, §18.1): the six cities and
# ranks 7–96. "City" in field names keeps meaning municipality (kunta).
CityId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]


class BodyKind(StrEnum):
    council = "council"
    board = "board"
    committee = "committee"
    section = "section"
    enterprise_board = "enterprise_board"


class Stage(StrEnum):
    agenda = "agenda"
    decisions = "decisions"
    minutes = "minutes"


class Role(StrEnum):
    member = "member"
    deputy = "deputy"
    chair = "chair"
    vice_chair = "vice_chair"
    youth_rep = "youth_rep"
    official = "official"


class SectionType(StrEnum):
    proposal = "proposal"
    deliberation = "deliberation"
    decision = "decision"
    background = "background"
    history = "history"
    statement = "statement"
    dissent = "dissent"
    other = "other"


class MotionKind(StrEnum):
    counter_proposal = "counter_proposal"
    send_back = "send_back"
    table = "table"
    resolution = "resolution"
    other = "other"


class Outcome(StrEnum):
    adopted = "adopted"
    rejected = "rejected"
    withdrawn = "withdrawn"
    unknown = "unknown"


class Choice(StrEnum):
    jaa = "jaa"
    ei = "ei"
    tyhja = "tyhja"
    poissa = "poissa"


class SpeechKind(StrEnum):
    speech = "speech"
    reply = "reply"


class Lang(StrEnum):
    fi = "fi"
    sv = "sv"
    mixed = "mixed"


class ItemStatus(StrEnum):
    active = "active"
    tombstone = "tombstone"


class VoteSource(StrEnum):
    html = "html"
    pdf = "pdf"


class AttachmentKind(StrEnum):
    attachment = "attachment"
    supplementary = "supplementary"


class City(_Model):
    id: CityId
    name_fi: str
    name_sv: str | None = None
    enabled: bool
    adapter: str


class Body(_Model):
    id: str
    city: CityId
    name_fi: str
    kind: BodyKind
    source_ids: dict[str, str] = Field(default_factory=dict)
    active_from: dt.date | None = None
    active_to: dt.date | None = None
    successor: str | None = None
    included: bool = True


class Term(_Model):
    city: CityId
    start: dt.date
    end: dt.date


class Election(_Model):
    """A person's candidacy in a municipal election (PLAN.md §8 source 4)."""

    year: int
    party: str
    result: str  # elected | deputy | not_elected
    votes: int | None = None
    source: str


class Person(_Model):
    id: str
    city: CityId
    name: str
    sort_name: str
    aliases: list[str] = Field(default_factory=list)
    wikidata: str | None = None
    party: str | None = None
    election: Election | None = None


class Membership(_Model):
    person_id: str
    body_id: str
    role: Role
    group: str | None = None
    party: str | None = None
    start: dt.date | None = None
    end: dt.date | None = None
    source: str


class PeopleFile(_Model):
    """data/{city}/people.json"""

    persons: list[Person]
    memberships: list[Membership]


class PersonRef(_Model):
    raw: str
    person_id: str | None = None
    confidence: float | None = None


class Attendance(_Model):
    person_ref: PersonRef
    role_text: str
    present: bool
    note: str | None = None


class Section(_Model):
    type: SectionType
    heading: str | None = None
    text: str


class Motion(_Model):
    kind: MotionKind
    proposer_ref: PersonRef
    seconder_refs: list[PersonRef] = Field(default_factory=list)
    text: str
    outcome: Outcome | None = None


class Counts(_Model):
    jaa: int = 0
    ei: int = 0
    tyhja: int = 0
    poissa: int = 0


class Ballot(_Model):
    person_ref: PersonRef
    choice: Choice
    group_text: str | None = None


class VoteEvent(_Model):
    ordinal: int
    jaa_label: str
    ei_label: str
    counts: Counts
    ballots: list[Ballot] = Field(default_factory=list)
    result_text: str | None = None
    source: VoteSource
    source_url: str
    needs_review: bool = False
    review_reason: str | None = None


class Attachment(_Model):
    title: str
    url: str
    kind: AttachmentKind = AttachmentKind.attachment


class AgendaItem(_Model):
    id: str
    meeting_id: str
    ordinal: int
    pykala: int | None = None
    title: str
    case_number: str | None = None
    presenter: str | None = None
    preparers: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    motions: list[Motion] = Field(default_factory=list)
    votes: list[VoteEvent] = Field(default_factory=list)
    statements: list[Section] = Field(default_factory=list)
    disqualified: list[PersonRef] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    decision_summary: str | None = None
    source_url: str
    source_ids: dict[str, str] = Field(default_factory=dict)
    content_sha256: str
    status: ItemStatus = ItemStatus.active


class Meeting(_Model):
    id: str
    body_id: str
    date: dt.date
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = None
    stage: Stage
    source_url: str
    source_ids: dict[str, str] = Field(default_factory=dict)
    minutes_pdf_url: str | None = None
    video_url: str | None = None
    attendance: list[Attendance] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)


class MeetingFile(_Model):
    """On-disk shape of data/{city}/meetings/{yyyy}/{body_slug}--{date}.json (§5.3)."""

    meeting: Meeting
    items: list[AgendaItem] = Field(default_factory=list)


class Speech(_Model):
    id: str
    meeting_id: str
    item_id: str | None = None
    ordinal: int
    speaker_ref: PersonRef
    speaker_title: str
    kind: SpeechKind = SpeechKind.speech
    lang: Lang = Lang.fi
    text: str
    video_offset_s: float | None = None
    source_url: str


class MeetingRef(_Model):
    """What an adapter's list_meetings returns before the full fetch."""

    body_id: str
    date: dt.date
    stage: Stage
    source_url: str
    source_ids: dict[str, str] = Field(default_factory=dict)
    same_day_index: int = 1  # 2, 3 … when the body met more than once that day (§5.1)


class ItemRef(_Model):
    meeting_id: str
    ordinal: int
    source_url: str
    source_ids: dict[str, str] = Field(default_factory=dict)
    stage: Stage = Stage.minutes
    title: str | None = None  # as printed on the meeting's agenda
    pykala: int | None = None
