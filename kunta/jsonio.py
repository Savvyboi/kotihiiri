"""Deterministic JSON writing (PLAN.md §2.2 rule 10).

Same input → byte-identical output: sorted keys, 2-space indent, trailing newline,
NFC-normalized strings. Files are only rewritten when their bytes change so a
no-change run leaves an empty git diff.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

import orjson
from pydantic import BaseModel

_OPTS = orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {_normalize(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize(v) for v in value]
    return value


def dumps(value: Any) -> bytes:
    return orjson.dumps(_normalize(value), option=_OPTS)


def write(path: Path, value: Any) -> bool:
    """Write `value` to `path` if the bytes differ. Returns True when the file changed."""
    data = dumps(value)
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return True


def read(path: Path) -> Any:
    return orjson.loads(path.read_bytes())
