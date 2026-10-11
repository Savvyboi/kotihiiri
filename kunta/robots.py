"""robots.txt matching per RFC 9309, including `*` and `$` wildcards.

`urllib.robotparser` only does plain prefix matching, so a rule like `Disallow: /*?*from=*`
(paatokset.hel.fi has several) never matches there and the URL would be fetched. This module
picks the group for our product token (else `*`), then applies the longest matching rule;
on a tie, Allow wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(rx + ("$" if anchored else ""))


def _norm(path: str) -> str:
    # Compare decoded forms so `%C3%A4` and `ä` match the same rule.
    return unquote(path)


class RobotsRules:
    def __init__(self, text: str = "", *, allow_all: bool = False, disallow_all: bool = False) -> None:
        self.allow_all = allow_all
        self.disallow_all = disallow_all
        self.groups = self._parse(text) if text else []

    @staticmethod
    def _parse(text: str) -> list[_Group]:
        groups: list[_Group] = []
        current: _Group | None = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (s.strip() for s in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = _Group()
                    groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
            elif key in ("allow", "disallow") and current is not None:
                last_was_agent = False
                if value:
                    current.rules.append((key == "allow", value))
            else:
                last_was_agent = False
        return groups

    def _rules_for(self, user_agent: str) -> list[tuple[bool, str]]:
        token = user_agent.split("/", 1)[0].strip().lower()
        named = [g for g in self.groups if any(a != "*" and a in token for a in g.agents)]
        chosen = named or [g for g in self.groups if "*" in g.agents]
        return [r for g in chosen for r in g.rules]

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        parts = urlsplit(url)
        target = _norm((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
        best: tuple[int, bool] | None = None
        for allow, pattern in self._rules_for(user_agent):
            if _compile(_norm(pattern)).match(target):
                key = (len(pattern), allow)
                if best is None or key > best:
                    best = key
        return True if best is None else best[1]
