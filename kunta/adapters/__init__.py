"""Adapter registry keyed by the `adapter` value in config/cities.yaml."""

from __future__ import annotations

from ..config import require_enabled
from ..http import PoliteClient
from .base import Adapter, NotEnabled
from .casem import CasemAdapter
from .dynasty import DynastyAdapter
from .helsinki import HelsinkiAdapter
from .turku import TurkuAdapter
from .tweb import TwebAdapter

ADAPTERS = {
    "helsinki": HelsinkiAdapter,
    "dynasty": DynastyAdapter,
    "casem": CasemAdapter,
    "tweb": TwebAdapter,
    "turku": TurkuAdapter,
}


def adapter_for(city: str, client: PoliteClient) -> Adapter:
    """Build the adapter for an enabled city. Disabled cities raise before any fetch."""
    try:
        cfg = require_enabled(city)
    except Exception as exc:
        raise NotEnabled(str(exc)) from exc
    adapter = ADAPTERS[cfg.adapter](client, cfg.base_urls[0])
    adapter.city = city
    return adapter


__all__ = ["ADAPTERS", "Adapter", "NotEnabled", "adapter_for"]
