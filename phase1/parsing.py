from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re


IGNORED_TAGS = {"script", "style", "noscript", "template"}
BLOCK_TAGS = {
    "article",
    "aside",
    "br",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}

WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    visible_text: str
    normalized_title: str
    normalized_text: str


def normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", unescape(text)).strip()


def normalize_for_search(text: str) -> str:
    return normalize_text(text).casefold()


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._inside_body = False
        self._inside_title = False
        self._inside_h1 = False
        self._title_parts: list[str] = []
        self._h1_parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in IGNORED_TAGS:
            self._ignored_depth += 1
            return

        if lowered == "body":
            self._inside_body = True
        elif lowered == "title":
            self._inside_title = True
        elif lowered == "h1":
            self._inside_h1 = True

        if self._inside_body and lowered in BLOCK_TAGS:
            self._text_parts.append(" ")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if self._ignored_depth == 0 and tag.lower() in BLOCK_TAGS:
            self._text_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return

        if lowered == "body":
            self._inside_body = False
        elif lowered == "title":
            self._inside_title = False
        elif lowered == "h1":
            self._inside_h1 = False

        if self._inside_body and lowered in BLOCK_TAGS:
            self._text_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth > 0:
            return

        if self._inside_title:
            self._title_parts.append(data)
        if self._inside_h1:
            self._h1_parts.append(data)

        if self._inside_body:
            self._text_parts.append(data)

    def get_document(self) -> ParsedDocument:
        title = normalize_text("".join(self._title_parts))
        if not title:
            title = normalize_text("".join(self._h1_parts))

        visible_text = normalize_text("".join(self._text_parts))
        return ParsedDocument(
            title=title,
            visible_text=visible_text,
            normalized_title=normalize_for_search(title),
            normalized_text=normalize_for_search(visible_text),
        )


def parse_document(html: str) -> ParsedDocument:
    parser = VisibleTextParser()
    parser.feed(html)
    parser.close()
    return parser.get_document()
