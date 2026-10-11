"""Adapter protocol (PLAN.md §6). Adapters only parse; networking lives in kunta.http."""

from __future__ import annotations

import datetime as dt
from typing import Protocol

from ..http import PoliteClient
from ..models import AgendaItem, Body, ItemRef, Meeting, MeetingRef, Speech, VoteEvent


class NotEnabled(RuntimeError):
    """The city is disabled in config/cities.yaml; the adapter must not fetch anything."""


class Adapter(Protocol):
    city: str

    def discover_bodies(self) -> list[Body]: ...
    def list_meetings(self, body: Body, since: dt.date, until: dt.date | None) -> list[MeetingRef]: ...
    def fetch_meeting(self, ref: MeetingRef) -> Meeting: ...
    def fetch_item(self, ref: ItemRef) -> AgendaItem: ...
    def fetch_votes(self, item: AgendaItem) -> list[VoteEvent]: ...
    def fetch_speeches(self, meeting: Meeting) -> list[Speech]: ...


class PendingAdapter:
    """Base for adapters whose milestone has not landed yet. Every method raises."""

    city: str = ""
    milestone: str = ""

    def __init__(self, client: PoliteClient, base_url: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")

    def _pending(self) -> NotImplementedError:
        return NotImplementedError(f"{self.city} adapter lands in {self.milestone} (PLAN.md §15)")

    def discover_bodies(self) -> list[Body]:
        raise self._pending()

    def list_meetings(self, body: Body, since: dt.date, until: dt.date | None) -> list[MeetingRef]:
        raise self._pending()

    def fetch_meeting(self, ref: MeetingRef) -> Meeting:
        raise self._pending()

    def fetch_item(self, ref: ItemRef) -> AgendaItem:
        raise self._pending()

    def fetch_votes(self, item: AgendaItem) -> list[VoteEvent]:
        return []

    def fetch_speeches(self, meeting: Meeting) -> list[Speech]:
        return []
