"""Which bodies are in scope (PLAN.md §1). Default: include unless the name matches an exclude
pattern. `config/bodies/{city}.yaml` can override per body with `included: true|false`.

Municipalities from the registry (§18.1) start with `bodies_scope: council_board`: only the council
and the municipal board are in scope until committees are switched on (§17). Swedish-language
municipalities (`lang: sv`) keep their Swedish council; elsewhere a Swedish body is a duplicate."""

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
    r"lapsivaltuusto",
    r"barnfullmäktige",
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
    # Swedish forms of the above (Swedish-language municipalities, §18.5)
    r"ungdomsfullmäktige",
    r"ungdomsråd",
    r"äldreråd",
    r"handikappråd",
    r"funktionshinderråd",
    r"centralvalnämnd",
    r"valnämnd",
    r"valbestyrelse",
]
_EXCLUDE = re.compile("|".join(EXCLUDE_PATTERNS), re.IGNORECASE)
# Swedish duplicates of Finnish documents (Vantaa's Stadsfullmäktige, Porvoo's Stadsstyrelsen), only in
# Finnish-language municipalities.
_SWEDISH_DUPLICATE = re.compile(r"^(stads|kommun)(fullmäktige|styrelsen?)$", re.IGNORECASE)
# Bilingual names ("Kunnanhallitus - Kommunstyrelsen"): the kind comes from the first part.
_BILINGUAL = re.compile(r"\s+[-–/]\s+")
_BOARD = re.compile(r"^(kaupungin|kunnan)?hallitus$|^(stads|kommun)styrelse(n)?$", re.IGNORECASE)


def _city_scope(city: str | None) -> tuple[str | None, str]:
    if not city:
        return None, "fi"
    from .config import load_cities

    cfg = load_cities().get(city)
    if cfg is None:
        return None, "fi"
    return cfg.extra.get("bodies_scope"), cfg.extra.get("lang", "fi")


def default_included(name_fi: str, city: str | None = None) -> bool:
    scope, lang = _city_scope(city)
    if _EXCLUDE.search(name_fi) or (lang != "sv" and _SWEDISH_DUPLICATE.search(name_fi)):
        return False
    if scope == "council_board":
        return guess_kind(name_fi) in (BodyKind.council, BodyKind.board)
    return True


def guess_kind(name_fi: str) -> BodyKind:
    n = _BILINGUAL.split(name_fi.lower().strip())[0]
    if "valtuusto" in n or "kyselytunti" in n or "fullmäktige" in n:
        return BodyKind.council
    if "jaosto" in n or "sektion" in n:
        return BodyKind.section
    if "johtokunta" in n or "direktion" in n:
        return BodyKind.enterprise_board
    if _BOARD.match(n):  # exact: "Kaupunginhallitus, strategiset yhtiöt" is a section-like body
        return BodyKind.board
    return BodyKind.committee


def overrides(city: str, config_dir: Path = CONFIG_DIR) -> dict[str, dict]:
    path = config_dir / "bodies" / f"{city}.yaml"
    if not path.exists():
        return {}
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("bodies") or {}


def is_included(city: str, body_slug: str, name_fi: str, config_dir: Path = CONFIG_DIR) -> bool:
    flag = overrides(city, config_dir).get(body_slug, {}).get("included")
    return default_included(name_fi, city) if flag is None else bool(flag)
