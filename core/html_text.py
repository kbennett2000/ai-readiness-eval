"""Minimal, dependency-free HTML -> text extraction (ADR-0005).

Deliberately simple and documented: drops script/style/nav-ish containers, keeps
visible text, and collapses whitespace. Extraction is lossy — that is stated in
ADR-0005, and the manifest records the resulting byte_size so sparse (e.g.
JS-rendered) pages are visible rather than hidden.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

_DROP_TAGS = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form"}
_BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "ul", "ol", "table", "tr",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "br", "header", "title",
}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_TAGS:
            self._drop_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in _DROP_TAGS and self._drop_depth > 0:
            self._drop_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._drop_depth == 0 and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def _collapse(text: str) -> str:
    # collapse runs of spaces/tabs, trim each line, drop >2 consecutive blank lines
    text = re.sub(r"[ \t]+", " ", text)
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[str] = []
    blanks = 0
    for ln in lines:
        if ln:
            out.append(ln)
            blanks = 0
        else:
            blanks += 1
            if blanks <= 1:
                out.append("")
    return "\n".join(out).strip() + "\n"


def html_to_text(html: str) -> str:
    """Return collapsed visible text from an HTML document."""
    parser = _Extractor()
    parser.feed(html)
    return _collapse(parser.text())
