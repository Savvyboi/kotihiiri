"""Flatten an HTML page into an ordered list of text blocks.

Parsers work on what a reader sees (headings, lines of text, tables, links) rather than on CSS
class names, which change with every theme update. A block is one heading, one line of text or
one table, in document order. `<br>` splits lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from .text import nfc

SKIP_TAGS = {
    "script", "style", "noscript", "template", "svg", "button", "form", "select", "option",
    "nav", "header", "footer", "iframe", "input", "label", "dialog",
}  # fmt: skip
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "dd", "details", "div", "dl", "dt", "fieldset",
    "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "main", "ol", "p",
    "pre", "section", "summary", "table", "ul", "caption", "tr", "td", "th", "tbody", "thead",
}  # fmt: skip
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


@dataclass
class Link:
    text: str
    href: str


@dataclass
class Block:
    kind: str  # "h1".."h6", "text" or "table"
    text: str = ""
    rows: list[list[str]] = field(default_factory=list)  # table rows incl. header row
    links: list[Link] = field(default_factory=list)

    @property
    def is_heading(self) -> bool:
        return self.kind in HEADINGS

    @property
    def level(self) -> int:
        return int(self.kind[1]) if self.is_heading else 0


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", nfc(text).replace("\xa0", " ")).strip()


def _has_block_child(node: Node) -> bool:
    child = node.child
    while child is not None:
        if child.tag in BLOCK_TAGS or (
            child.tag not in SKIP_TAGS and child.tag != "-text" and _has_block_child(child)
        ):
            return True
        child = child.next
    return False


def _inline_lines(node: Node) -> list[str]:
    """Text of an inline-only element, split at <br>."""
    parts: list[str] = []
    buf: list[str] = []

    def walk(n: Node) -> None:
        child = n.child
        while child is not None:
            if child.tag == "-text":
                buf.append(child.text_content or "")
            elif child.tag == "br":
                parts.append("".join(buf))
                buf.clear()
            elif child.tag not in SKIP_TAGS:
                walk(child)
            child = child.next

    walk(node)
    parts.append("".join(buf))
    return [c for c in (clean(p) for p in parts) if c]


def _links(node: Node, base: str) -> list[Link]:
    out = []
    for a in node.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
            out.append(Link(clean(a.text(deep=True, separator=" ")), urljoin(base, href)))
    if node.tag == "a" and (href := (node.attributes.get("href") or "").strip()):
        out.append(Link(clean(node.text(deep=True, separator=" ")), urljoin(base, href)))
    return out


def _table(node: Node) -> list[list[str]]:
    rows = []
    for tr in node.css("tr"):
        cells = [clean(c.text(deep=True, separator=" ")) for c in tr.css("th, td")]
        if any(cells):
            rows.append(cells)
    return rows


def blocks(html: str, base: str = "") -> list[Block]:
    tree = HTMLParser(html)
    root = tree.css_first("main") or tree.body or tree.root
    out: list[Block] = []

    def emit_lines(node: Node) -> None:
        links = _links(node, base)
        lines = _inline_lines(node)
        for i, line in enumerate(lines):
            out.append(Block("text", line, links=links if i == 0 else []))

    def walk(node: Node) -> None:
        child = node.child
        pending: list[Node] = []  # consecutive inline siblings inside a block container

        def flush() -> None:
            if not pending:
                return
            text_lines: list[str] = []
            links: list[Link] = []
            for n in pending:
                if n.tag == "-text":
                    t = clean(n.text_content or "")
                    if t:
                        text_lines.append(t)
                elif n.tag == "br":
                    text_lines.append("\n")
                else:
                    text_lines.extend(_inline_lines(n) or [])
                    links.extend(_links(n, base))
            joined = " ".join(text_lines)
            for i, line in enumerate(c for c in (clean(x) for x in joined.split("\n")) if c):
                out.append(Block("text", line, links=links if i == 0 else []))
            pending.clear()

        while child is not None:
            tag = child.tag
            if tag in SKIP_TAGS or tag == "-comment":
                pass
            elif tag in HEADINGS:
                flush()
                text = clean(child.text(deep=True, separator=" "))
                if text:
                    out.append(Block(tag, text, links=_links(child, base)))
            elif tag == "table":
                flush()
                out.append(Block("table", rows=_table(child)))
            elif tag in BLOCK_TAGS or _has_block_child(child):
                flush()
                if _has_block_child(child):
                    walk(child)
                else:
                    emit_lines(child)
            else:
                pending.append(child)
            child = child.next
        flush()

    walk(root)
    return out


def iframe_srcs(html: str, base: str = "") -> list[str]:
    tree = HTMLParser(html)
    return [urljoin(base, n.attributes.get("src") or "") for n in tree.css("iframe[src]")]


def all_links(html: str, base: str = "") -> list[Link]:
    """Every link on the page, navigation included (body discovery reads the menu)."""
    tree = HTMLParser(html)
    return _links(tree.root, base) if tree.root else []
