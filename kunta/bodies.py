"""Which bodies are in scope (PLAN.md §1). Default: include unless the name matches an exclude
pattern. `config/bodies/{city}.yaml` can override per body with `included: true|false`."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import CONFIG_DIR
from .models import BodyKind

EXCLUDE_PATTERNS = [
    # advisory / influence bodies
    r"nuorisoneuvosto",
    r"nuorisovaltuusto",
    r"maahanmuuttajaneuvosto",
    r"eläkeläisvaltuusto",
    r"päihdeneuvosto",
    r"nuorten vaikuttajaryhmä",
    r"vanhusneuvosto",
    r"vammaisneuvosto",
    r"monikulttuurisuusasiain neuvottelukunta",
    r"monikulttuurisuusneuvosto",
    r"aluetoimikunta",
    r"aluelautakunta",
    r"kehittämistoimikunta",
    r"seurantaryhmä",
    r"neuvottelukunta",
    # election committees
    r"keskusvaalilautakunta",
    r"aluevaalilautakunta",
    r"vaalilautakunta",
    r"vaalitoimikunta",
    # test bodies
    r"testi",
    r"versiopäivitystoimielin",
    # individual welfare, student or permit cases
    r"yksilöasioiden jaosto",
    r"lupajaosto",
    r"ympäristö- ja lupajaosto",
    r"oikeusturvatoimielin",
    r"näyttöjen toimielin",
    # Swedish duplicates of Finnish documents
    r"^stadsfullmäktige$",
]
_EXCLUDE = re.compile("|".join(EXCLUDE_PATTERNS), re.IGNORECASE)


def default_included(name_fi: str) -> bool:
    return not _EXCLUDE.search(name_fi)


def guess_kind(name_fi: str) -> BodyKind:
    n = name_fi.lower()
    if "valtuusto" in n or "kyselytunti" in n:
        return BodyKind.council
    if "jaosto" in n:
        return BodyKind.section
    if "johtokunta" in n:
        return BodyKind.enterprise_board
    if "kaupunginhallitus" in n:
        return BodyKind.board
    return BodyKind.committee


def overrides(city: str, config_dir: Path = CONFIG_DIR) -> dict[str, dict]:
    path = config_dir / "bodies" / f"{city}.yaml"
    if not path.exists():
        return {}
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("bodies") or {}


def is_included(city: str, body_slug: str, name_fi: str, config_dir: Path = CONFIG_DIR) -> bool:
    flag = overrides(city, config_dir).get(body_slug, {}).get("included")
    return default_included(name_fi) if flag is None else bool(flag)
