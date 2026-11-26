"""AI briefs of meetings, agenda items and votes (PLAN.md §20).

A free language model on OpenRouter reads each meeting's minutes and writes, in the language of the
minutes:

- a two-to-three sentence summary of the meeting and up to four highlights;
- a one-to-two sentence brief per substantive agenda item;
- one sentence per vote saying what Jaa and Ei meant and which side won.

Storage keeps the site's file count flat: one file per municipality and year,
`data/{city}/briefs/{yyyy}.json`, keyed by meeting id. Each entry records the hash of what the model
read (`input_sha256`), so a run only sends meetings that are new or whose minutes changed, and the
site hides an item brief whose item has changed since (`sha`). Model output is never regenerated
for unchanged input, which keeps the data deterministic run to run (§2.2 rule 10).

Free models are rate limited (OpenRouter: 20 requests a minute; 50 a day, or 1,000 a day once the
account has bought at least $10 of credits), so one request covers a whole meeting, procedural
items (opening, quorum, minute checkers) are never sent, and a run stops at `max_requests` or at
the first daily-limit answer and picks up where it left off next time. Newest meetings of the six
cities go first.

The key comes from the OPENROUTER_API_KEY environment variable and is never written anywhere.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import jsonio
from .config import DATA_DIR, load_cities
from .text import collapse_ws, is_confidential, strip_pii

log = logging.getLogger("kunta.briefs")

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"
# Tried in order: OpenRouter falls through to the next one when a model is down or rate limited.
# Free model ids change; `kunta briefs --list-models` prints the current free ones.
DEFAULT_MODELS = (
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-nano-9b-v2:free",
)
PROMPT_VERSION = 1

# Characters of source text per request and per part of an item. Finnish runs about 3 characters a
# token, so a full request stays near 15k tokens: far inside free models' context, and few enough
# requests that the six cities' backlog since 2025 is about 2,800 requests.
CHUNK_CHARS = 45_000
CHUNK_ITEMS = 25  # more briefs than this in one answer and free models start dropping some
ITEM_PART_CHARS = 1_800
MOTION_CHARS = 400
# Output limits; longer answers are cut at a sentence.
SUMMARY_CHARS = 600
HIGHLIGHT_CHARS = 220
BRIEF_CHARS = 420
VOTE_CHARS = 320
MAX_HIGHLIGHTS = 4

_PROCEDURAL = re.compile(
    r"^\s*(?:kokouksen\s+(?:avaaminen|avaus|laillisuus|järjestäytyminen)|laillisuus\s+ja\s+päätösvaltaisuus|"
    r"läsnäolo|nimenhuuto|pöytäkirjan\s+tarkast|pöytäkirjantarkast|työjärjestyksen|esityslistan\s+hyväksy|"
    r"ilmoitusasiat|tiedoksi\s+merkittävät|tiedoksi\s+saatetut|kokouksen\s+päättäminen|"
    r"mötets\s+(?:öppnande|laglighet)|laglighet\s+och\s+beslutförhet|protokolljusterar|val\s+av\s+protokolljusterare|"
    r"justering\s+av\s+protokoll|anmälningsärenden)",
    re.IGNORECASE,
)


def is_procedural(title: str) -> bool:
    return bool(_PROCEDURAL.match(title)) or is_confidential(title)


# ---------------------------------------------------------------------------------------------- input


def _clip(text: str, limit: int) -> str:
    text = collapse_ws(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    dot = cut.rfind(". ")
    return (cut[: dot + 1] if dot > limit * 0.6 else cut.rstrip()) + " […]"


def _section(item: dict[str, Any], *types: str) -> str:
    return "\n".join(s["text"] for s in item.get("sections", []) if s.get("type") in types)


def item_block(item: dict[str, Any]) -> str:
    """What the model reads about one agenda item."""
    lines = [f"### Asia {item['ordinal']}: {item['title']}"]
    decision = _section(item, "decision") or item.get("decision_summary") or ""
    proposal = _section(item, "proposal")
    background = _section(item, "background", "deliberation", "other")
    if decision:
        lines.append("Päätös: " + _clip(decision, ITEM_PART_CHARS))
    if proposal and proposal != decision:
        lines.append("Päätösehdotus: " + _clip(proposal, ITEM_PART_CHARS))
    if background:
        lines.append("Perustelut: " + _clip(background, ITEM_PART_CHARS))
    for m in item.get("motions", []):
        who = m.get("proposer_ref", {}).get("raw", "")
        outcome = f" ({m['outcome']})" if m.get("outcome") else ""
        text = _clip(m.get("text", ""), MOTION_CHARS)
        lines.append(f"Ehdotus ({m.get('kind', 'other')}, {who}){outcome}: {text}")
    for v in item.get("votes", []):
        c = v.get("counts", {})
        lines.append(
            f"Äänestys {v['ordinal']}: Jaa = {_clip(v.get('jaa_label') or '-', 300)}; "
            f"Ei = {_clip(v.get('ei_label') or '-', 300)}; tulos jaa {c.get('jaa', 0)}, ei {c.get('ei', 0)}, "
            f"tyhjä {c.get('tyhja', 0)}, poissa {c.get('poissa', 0)}"
            + (f"; {_clip(v['result_text'], 200)}" if v.get("result_text") else "")
        )
    return "\n".join(lines)


def substantive_items(file: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        i for i in file["items"] if i.get("status", "active") != "tombstone" and not is_procedural(i["title"])
    ]


def input_sha256(file: dict[str, Any]) -> str:
    """Changes when anything the model would read changes (and when the prompt changes)."""
    h = hashlib.sha256(f"v{PROMPT_VERSION}\x00{file['meeting'].get('stage', '')}".encode())
    for i in substantive_items(file):
        h.update(f"\x00{i['ordinal']}:{i.get('content_sha256', '')}:{len(i.get('votes', []))}".encode())
    return h.hexdigest()


def chunks(items: list[dict[str, Any]], limit: int | None = None) -> list[list[dict[str, Any]]]:
    limit = limit or CHUNK_CHARS
    out: list[list[dict[str, Any]]] = []
    size = 0
    for it in items:
        n = len(item_block(it))
        if out and size + n <= limit and len(out[-1]) < CHUNK_ITEMS:
            out[-1].append(it)
            size += n
        else:
            out.append([it])
            size = n
    return out


# --------------------------------------------------------------------------------------------- prompt

_LANG = {"fi": "suomeksi", "sv": "på svenska"}

SYSTEM = """Olet kunnallispolitiikkaa seuraavan kansalaispalvelun toimittaja. Kirjoitat lyhyitä, \
selkeitä ja puolueettomia tiivistelmiä kunnan toimielinten pöytäkirjoista tavalliselle lukijalle.

Säännöt:
- Kerro vain se, mikä lähteessä lukee. Älä arvaa, älä lisää taustatietoa äläkä arvioi päätöksiä.
- Selkokieli: lyhyet lauseet, ei virkakieltä, ei lyhenteitä selittämättä. Mainitse rahasummat, \
paikat ja päivämäärät, jos ne ovat olennaisia.
- Älä mainitse henkilöiden nimiä, paitsi ehdotuksen tekijä äänestyksen kuvauksessa.
- Äänestyksen kuvaus: mitä Jaa ja Ei tarkoittivat ja kumpi voitti äänin X–Y.
- Vastaa pelkkänä JSON-objektina ilman muuta tekstiä."""

SCHEMA = """{
  "summary": "2–3 virkettä: mitä kokouksessa päätettiin tärkeimmistä asioista",
  "highlights": ["enintään 4 lyhyttä nostoa tärkeimmistä päätöksistä"],
  "items": [
    {"ordinal": 3, "brief": "1–2 virkettä: mitä asiassa päätettiin ja mitä se tarkoittaa",
     "votes": [{"ordinal": 1, "brief": "1 virke: mistä äänestettiin ja tulos"}]}
  ]
}"""


def messages(
    meeting: dict[str, Any],
    body_name: str,
    city_name: str,
    items: list[dict[str, Any]],
    lang: str,
    *,
    with_summary: bool,
) -> list[dict[str, str]]:
    stage = {"minutes": "pöytäkirja", "decisions": "päätöstiedote", "agenda": "esityslista"}.get(
        meeting.get("stage", ""), "pöytäkirja"
    )
    ask = (
        "Kirjoita kokoukselle tiivistelmä ja nostot sekä jokaiselle alla olevalle asialle oma tiivistelmä."
        if with_summary
        else "Kirjoita jokaiselle alla olevalle asialle oma tiivistelmä. "
        "Jätä summary tyhjäksi ja highlights tyhjäksi listaksi."
    )
    if stage == "esityslista":
        ask += " Tämä on esityslista: asioista ei ole vielä päätetty, joten kerro mitä ehdotetaan."
    user = (
        f"{city_name} – {body_name}, kokous {meeting['date']} ({stage}).\n"
        f"{ask} Kirjoita {_LANG.get(lang, 'suomeksi')}. Käytä asioiden ja äänestysten numeroita (ordinal) "
        "täsmälleen sellaisina kuin ne on annettu. "
        "Jos asia on rutiininomainen, kirjoita yksi lyhyt virke.\n\n"
        f"Vastausmuoto:\n{SCHEMA}\n\n" + "\n\n".join(item_block(i) for i in items)
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def summary_messages(
    meeting: dict[str, Any], body_name: str, city_name: str, item_briefs: list[tuple[str, str]], lang: str
) -> list[dict[str, str]]:
    """Second pass for meetings too long for one request: summary from the item briefs."""
    listing = "\n".join(f"- {title}: {brief}" for title, brief in item_briefs)
    user = (
        f"{city_name} – {body_name}, kokous {meeting['date']}. Alla on kokouksen asiat tiivistelminä. "
        f"Kirjoita {_LANG.get(lang, 'suomeksi')} kokoukselle tiivistelmä (2–3 virkettä) "
        "ja enintään 4 nostoa.\n\n"
        'Vastausmuoto:\n{"summary": "...", "highlights": ["..."]}\n\n' + listing
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


# --------------------------------------------------------------------------------------------- output

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def parse_json(text: str) -> dict[str, Any]:
    """The model's answer as a dict: tolerates reasoning blocks, code fences and chatter around it."""
    text = _THINK.sub("", text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the answer")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise ValueError("answer is not a JSON object")
    return obj


def clean(text: Any, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    text = strip_pii(collapse_ws(_THINK.sub("", text))).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > limit // 3 else cut.rstrip() + "…"


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def item_entries(answer: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{ordinal: {brief, sha, votes?}} for the items that were sent; anything else is dropped."""
    by_ordinal = {i["ordinal"]: i for i in items}
    out: dict[str, dict[str, Any]] = {}
    raw = answer.get("items")
    if isinstance(raw, dict):  # {"3": {...}} instead of a list
        raw = [{"ordinal": k, **v} for k, v in raw.items() if isinstance(v, dict)]
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        item = by_ordinal.get(_int(entry.get("ordinal")))
        brief = clean(entry.get("brief"), BRIEF_CHARS)
        if not item or not brief:
            continue
        rec: dict[str, Any] = {"brief": brief, "sha": item.get("content_sha256", "")}
        known = {v["ordinal"] for v in item.get("votes", [])}
        votes = {}
        for v in entry.get("votes") or []:
            if isinstance(v, dict) and _int(v.get("ordinal")) in known:
                text = clean(v.get("brief"), VOTE_CHARS)
                if text:
                    votes[str(_int(v["ordinal"]))] = text
        if votes:
            rec["votes"] = votes
        out[str(item["ordinal"])] = rec
    return out


def highlights(answer: dict[str, Any]) -> list[str]:
    raw = answer.get("highlights")
    items = [clean(h, HIGHLIGHT_CHARS) for h in raw] if isinstance(raw, list) else []
    return [h for h in items if h][:MAX_HIGHLIGHTS]


# --------------------------------------------------------------------------------------------- client


class DailyLimit(RuntimeError):
    """The free-model quota for today is used up; try again tomorrow."""


class ModelError(RuntimeError):
    pass


@dataclass
class OpenRouter:
    api_key: str
    models: tuple[str, ...] = DEFAULT_MODELS
    min_interval_s: float = 3.5  # 20 requests a minute on free models
    timeout_s: float = 180.0
    sleep: Callable[[float], None] = time.sleep
    transport: httpx.BaseTransport | None = None
    requests: int = 0
    _last: float = field(default=0.0, repr=False)
    _http: httpx.Client | None = field(default=None, repr=False)

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout_s, transport=self.transport)
        return self._http

    def close(self) -> None:
        if self._http is not None:
            self._http.close()

    def chat(self, msgs: list[dict[str, str]]) -> tuple[str, str]:
        """(content, model that answered). Counts every request sent, including retries."""
        payload: dict[str, Any] = {
            "model": self.models[0],
            "messages": msgs,
            "temperature": 0.2,
            "max_tokens": 6000,
            # Nemotron and other reasoning models: keep the thinking out of the answer.
            "reasoning": {"exclude": True},
        }
        if len(self.models) > 1:
            payload["models"] = list(self.models)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://kotihiiri.eu",
            "X-Title": "Kotihiiri",
        }
        for attempt in range(4):
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                r = self._client().post(API_URL, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                log.warning("openrouter: %s; retrying", exc)
                self.sleep(10 * (attempt + 1))
                continue
            if r.status_code == 429:
                body = r.text.lower()
                if "per-day" in body or "per day" in body or "daily" in body:
                    raise DailyLimit(r.text[:300])
                self.sleep(float(r.headers.get("retry-after") or 20 * (attempt + 1)))
                continue
            if r.status_code in (401, 402, 403):
                raise ModelError(f"openrouter {r.status_code}: {r.text[:300]}")
            if r.status_code >= 500 or r.status_code == 408:
                self.sleep(10 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise ModelError(f"openrouter {r.status_code}: {r.text[:300]}")
            data = r.json()
            if data.get("error"):
                raise ModelError(str(data["error"])[:300])
            try:
                content = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise ModelError(f"unexpected answer: {str(data)[:300]}") from exc
            return content, data.get("model") or self.models[0]
        raise ModelError("openrouter: gave up after 4 attempts")


def free_models(transport: httpx.BaseTransport | None = None) -> list[tuple[str, int]]:
    with httpx.Client(timeout=30, transport=transport) as c:
        data = c.get(MODELS_URL).json()["data"]
    return sorted((m["id"], int(m.get("context_length") or 0)) for m in data if m["id"].endswith(":free"))


# ----------------------------------------------------------------------------------------------- runs


@dataclass
class Pending:
    city: str
    path: Path
    meeting_id: str
    date: str
    rank: int
    sha: str


@dataclass
class Report:
    written: int = 0
    skipped_budget: int = 0
    failed: list[str] = field(default_factory=list)
    stopped: str | None = None
    requests: int = 0
    pending: int = 0

    def summary(self) -> str:
        s = (
            f"briefs: written={self.written} failed={len(self.failed)} requests={self.requests} "
            f"still_pending={self.pending}"
        )
        return s + (f" stopped: {self.stopped}" if self.stopped else "")


def briefs_path(city: str, year: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / city / "briefs" / f"{year}.json"


def load_briefs(city: str, data_dir: Path = DATA_DIR) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in sorted((data_dir / city / "briefs").glob("*.json")):
        out.update(jsonio.read(p))
    return out


def _meeting_files(city: str, data_dir: Path) -> Iterable[Path]:
    return sorted((data_dir / city / "meetings").glob("*/*.json"))


def find_pending(
    cities: list[str], data_dir: Path = DATA_DIR, *, since: str = "2025-01-01", agendas: bool = False
) -> list[Pending]:
    """Meetings whose brief is missing or out of date, newest first, the six cities first."""
    cfg = load_cities()
    out: list[Pending] = []
    for city in cities:
        rank = int(cfg[city].extra.get("rank", 99)) if city in cfg else 99
        have = load_briefs(city, data_dir)
        for path in _meeting_files(city, data_dir):
            file = jsonio.read(path)
            m = file["meeting"]
            if m["date"] < since or (m.get("stage") == "agenda" and not agendas):
                continue
            if not substantive_items(file):
                continue
            sha = input_sha256(file)
            if have.get(m["id"], {}).get("input_sha256") == sha:
                continue
            out.append(Pending(city, path, m["id"], m["date"], rank, sha))
    out.sort(key=lambda p: (p.rank > 6, _neg_date(p.date), p.meeting_id))
    return out


def _neg_date(d: str) -> int:
    return -dt.date.fromisoformat(d).toordinal()


def _names(city: str, data_dir: Path) -> tuple[dict[str, str], str, str]:
    cfg = load_cities().get(city)
    bodies_file = data_dir / city / "bodies.json"
    bodies = {b["id"]: b["name_fi"] for b in jsonio.read(bodies_file)} if bodies_file.exists() else {}
    lang = str(cfg.extra.get("lang", "fi")) if cfg else "fi"
    return bodies, (cfg.name_fi if cfg else city), lang


def brief_meeting(client: OpenRouter, file: dict[str, Any], body_name: str, city_name: str, lang: str):
    """The brief entry for one meeting (without input_sha256). Raises ModelError/DailyLimit."""
    meeting = file["meeting"]
    parts = chunks(substantive_items(file))
    entries: dict[str, dict[str, Any]] = {}
    summary, hl, model = "", [], ""
    for n, part in enumerate(parts):
        msgs = messages(meeting, body_name, city_name, part, lang, with_summary=len(parts) == 1)
        content, model = client.chat(msgs)
        try:
            answer = parse_json(content)
        except ValueError:
            # One retry: free models sometimes answer with prose or cut JSON.
            content, model = client.chat(msgs)
            answer = parse_json(content)
        entries.update(item_entries(answer, part))
        if len(parts) == 1:
            summary, hl = clean(answer.get("summary"), SUMMARY_CHARS), highlights(answer)
        log.debug("%s: part %d/%d done", meeting["id"], n + 1, len(parts))
    if len(parts) > 1 and entries:
        titles = {str(i["ordinal"]): i["title"] for i in file["items"]}
        listing = [(titles[k], v["brief"]) for k, v in sorted(entries.items(), key=lambda kv: int(kv[0]))]
        content, model = client.chat(summary_messages(meeting, body_name, city_name, listing, lang))
        answer = parse_json(content)
        summary, hl = clean(answer.get("summary"), SUMMARY_CHARS), highlights(answer)
    if not summary and not entries:
        raise ModelError("empty answer")
    rec: dict[str, Any] = {"model": model, "lang": lang, "stage": meeting.get("stage", ""), "items": entries}
    if summary:
        rec["summary"] = summary
    if hl:
        rec["highlights"] = hl
    return rec


def requests_needed(file: dict[str, Any]) -> int:
    n = len(chunks(substantive_items(file)))
    return n + (1 if n > 1 else 0)


def save(city: str, entries: dict[str, dict[str, Any]], data_dir: Path = DATA_DIR) -> None:
    """Merge {meeting_id: entry} into the city's per-year files."""
    by_year: dict[str, dict[str, dict[str, Any]]] = {}
    for mid, e in entries.items():
        by_year.setdefault(mid.rsplit("/", 1)[1][:4], {})[mid] = e
    for year, new in by_year.items():
        path = briefs_path(city, year, data_dir)
        cur = jsonio.read(path) if path.exists() else {}
        cur.update(new)
        jsonio.write(path, cur)


def prune(city: str, data_dir: Path = DATA_DIR) -> int:
    """Drop briefs of meetings that no longer exist (removed at the source or renamed)."""
    live = {jsonio.read(p)["meeting"]["id"] for p in _meeting_files(city, data_dir)}
    dropped = 0
    for path in sorted((data_dir / city / "briefs").glob("*.json")):
        cur = jsonio.read(path)
        keep = {k: v for k, v in cur.items() if k in live}
        dropped += len(cur) - len(keep)
        if keep:
            jsonio.write(path, keep)
        else:
            path.unlink()
    return dropped


def run(
    cities: list[str],
    client: OpenRouter,
    *,
    data_dir: Path = DATA_DIR,
    max_requests: int = 40,
    since: str = "2025-01-01",
    agendas: bool = False,
    max_minutes: float | None = None,
) -> Report:
    report = Report()
    for city in cities:
        if any(_meeting_files(city, data_dir)):
            prune(city, data_dir)
    pending = find_pending(cities, data_dir, since=since, agendas=agendas)
    deadline = time.monotonic() + max_minutes * 60 if max_minutes else None
    names = {c: _names(c, data_dir) for c in {p.city for p in pending}}
    for i, p in enumerate(pending):
        if deadline and time.monotonic() > deadline:
            report.stopped = "time"
            report.pending = report.skipped_budget + len(pending) - i
            break
        file = jsonio.read(p.path)
        need = requests_needed(file)
        if client.requests + need > max_requests:
            report.skipped_budget += 1
            continue
        bodies, city_name, lang = names[p.city]
        body = bodies.get(file["meeting"]["body_id"], file["meeting"]["body_id"].split("/")[1])
        try:
            entry = brief_meeting(client, file, body, city_name, lang)
        except DailyLimit as exc:
            report.stopped = f"daily limit ({exc})"
            report.pending = report.skipped_budget + len(pending) - i
            break
        except (ModelError, ValueError) as exc:
            log.warning("%s: %s", p.meeting_id, exc)
            report.failed.append(p.meeting_id)
            continue
        entry["input_sha256"] = p.sha
        save(p.city, {p.meeting_id: entry}, data_dir)  # after every meeting, so a crash loses nothing
        report.written += 1
        log.info("%s: brief written (%d items)", p.meeting_id, len(entry["items"]))
    else:
        report.pending = report.skipped_budget
    report.requests = client.requests
    if report.stopped is None and report.skipped_budget:
        report.stopped = "request budget"
    return report


def api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY") or None
