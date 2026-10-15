"""Adapter registry keyed by the `adapter` value in config/cities.yaml."""

from __future__ import annotations

from ..config import CityConfig, require_enabled
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
    return build_adapter(city, cfg, client)


def build_adapter(city: str, cfg: CityConfig, client: PoliteClient) -> Adapter:
    """The adapter for one municipality's config, enabled or not. Only `adapter_for` (crawls) and
    the robots audit (listing pages of hosts that allow them) call this."""
    adapter = ADAPTERS[cfg.adapter](client, cfg.base_urls[0])
    adapter.city = city
    if hasattr(adapter, "configure"):
        adapter.configure(cfg.extra)
    return adapter


__all__ = ["ADAPTERS", "Adapter", "NotEnabled", "adapter_for", "build_adapter"]
