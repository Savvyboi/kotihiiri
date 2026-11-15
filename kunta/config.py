"""Loading of config/*.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache" / "raw"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class CityConfig:
    id: str
    name_fi: str
    enabled: bool
    adapter: str
    base_urls: list[str]
    name_sv: str | None = None
    reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RobotsOverride:
    """Municipalities crawled although their robots.txt disallows us (PLAN.md §2.1 rule 1b).

    Off unless `enabled` is true in config/project.yaml. It only overrides Allow/Disallow rules in
    a robots.txt the host served: a host that answers 401/403, errors on robots.txt or refuses us
    during the run is never crawled. Hosts under it get `min_interval_s` between requests (or the
    host's Crawl-delay, if longer) instead of the usual 1 second.
    """

    enabled: bool = False
    municipalities: tuple[str, ...] = ()
    min_interval_s: float = 5.0
    approved_by: str | None = None
    approved_on: str | None = None

    def applies_to(self, slug: str) -> bool:
        return self.enabled and slug in self.municipalities


@dataclass(frozen=True)
class ProjectConfig:
    site_name: str
    site_domain: str | None
    contact_email: str | None
    user_agent_template: str
    since: str
    features: dict[str, bool]
    # host → path prefixes Savvas has allowed despite robots.txt (PLAN.md §2.1 rule 1, §17); each
    # entry in config/project.yaml names who approved it and when. Only commands that pass these
    # to the client use them.
    robots_exceptions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    robots_override: RobotsOverride = field(default_factory=RobotsOverride)

    @property
    def user_agent(self) -> str:
        """The crawler User-Agent. Raises if the placeholders are unset (§2.1 rule 3)."""
        if not self.site_domain or not self.contact_email:
            raise ConfigError("config/project.yaml: set site_domain and contact_email before crawling")
        return self.user_agent_template.format(site_domain=self.site_domain, contact_email=self.contact_email)


_PARSED: dict[Path, tuple[float, dict[str, Any]]] = {}


def _load(name: str, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    # Parsed once per file version: body scope checks read the 96-entry registry per body.
    path = config_dir / name
    mtime = path.stat().st_mtime
    hit = _PARSED.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    _PARSED[path] = (mtime, data)
    return data


def load_project(config_dir: Path = CONFIG_DIR) -> ProjectConfig:
    raw = _load("project.yaml", config_dir)
    return ProjectConfig(
        site_name=raw.get("site_name", ""),
        site_domain=raw.get("site_domain"),
        contact_email=raw.get("contact_email"),
        user_agent_template=raw["user_agent_template"],
        since=str(raw.get("since", "2025-01-01")),
        features=dict(raw.get("features") or {}),
        robots_exceptions=_robots_exceptions(raw.get("robots_exceptions") or []),
        robots_override=_robots_override(raw.get("robots_override") or {}),
    )


def _robots_override(raw: dict[str, Any]) -> RobotsOverride:
    if not raw:
        return RobotsOverride()
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("config/project.yaml robots_override.enabled must be true or false")
    slugs = tuple(str(s) for s in raw.get("municipalities") or [])
    if len(set(slugs)) != len(slugs):
        raise ConfigError("config/project.yaml robots_override.municipalities lists a slug twice")
    interval = float(raw.get("min_interval_s", 5.0))
    if interval < 1.0:
        # Never faster than the normal crawl (§2.1 rule 4).
        raise ConfigError("config/project.yaml robots_override.min_interval_s must be at least 1")
    if enabled and not (raw.get("approved_by") and raw.get("approved_on")):
        raise ConfigError(
            "config/project.yaml robots_override needs approved_by and approved_on to be enabled"
        )
    return RobotsOverride(
        enabled=enabled,
        municipalities=slugs,
        min_interval_s=interval,
        approved_by=raw.get("approved_by"),
        approved_on=str(raw["approved_on"]) if raw.get("approved_on") else None,
    )


def _robots_exceptions(entries: list[dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for e in entries:
        if not (e.get("host") and e.get("paths") and e.get("approved_by") and e.get("approved_on")):
            raise ConfigError(
                "config/project.yaml robots_exceptions: each entry needs host, paths, "
                "approved_by and approved_on"
            )
        out[str(e["host"])] = tuple(str(p) for p in e["paths"])
    return out


_KNOWN = {"name_fi", "name_sv", "enabled", "adapter", "base_urls", "reason"}


def load_cities(config_dir: Path = CONFIG_DIR) -> dict[str, CityConfig]:
    """All 96 municipalities from config/municipalities.yaml (generated by `kunta registry` from
    config/cities.yaml and the registry, PLAN.md §18.1), in rank order."""
    raw = _load("municipalities.yaml", config_dir)["municipalities"]
    return {
        cid: CityConfig(
            id=cid,
            name_fi=c["name_fi"],
            name_sv=c.get("name_sv"),
            enabled=bool(c["enabled"]),
            adapter=c["adapter"],
            base_urls=list(c.get("base_urls") or []),
            reason=c.get("reason"),
            extra={k: v for k, v in c.items() if k not in _KNOWN},
        )
        for cid, c in raw.items()
    }


def require_enabled(city: str, config_dir: Path = CONFIG_DIR) -> CityConfig:
    cities = load_cities(config_dir)
    if city not in cities:
        raise ConfigError(f"unknown city {city!r}")
    cfg = cities[city]
    if not cfg.enabled:
        raise ConfigError(f"{city} is disabled ({cfg.reason}); see config/municipalities.yaml")
    return cfg
