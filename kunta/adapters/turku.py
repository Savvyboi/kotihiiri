"""Turku: not written yet (PLAN.md §7.6). Covered by the robots override once it exists."""

from __future__ import annotations

from ..http import PoliteClient
from .base import NotEnabled


class TurkuAdapter:
    city = "turku"

    def __init__(self, client: PoliteClient, base_url: str) -> None:
        raise NotEnabled("turku: no_adapter")
