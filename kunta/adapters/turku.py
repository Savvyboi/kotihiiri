"""Turku: disabled until the city grants permission (PLAN.md §2.1 rule 2, §7.6)."""

from __future__ import annotations

from ..http import PoliteClient
from .base import NotEnabled


class TurkuAdapter:
    city = "turku"

    def __init__(self, client: PoliteClient, base_url: str) -> None:
        raise NotEnabled("turku: robots_disallow_pending_permission")
