from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re

from phase1.parsing import normalize_text, parse_document


IGNORED_TAGS = {"script", "style", "noscript", "template"}
HEADING_TAGS = {"h1", "h2", "h3"}
CHUNK_TAGS = {"li", "p", "td", "th"}
TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+")


@dataclass(frozen=True)
class DocumentChunk:
    doc_id: str
    title: str
    section_path: str
    text: str
    ordinal: int
    token_count: int

    @property
    def chunk_id(self) -> str:
        return f"{self.doc_id}:{self.ordinal:04d}"

    @property
    def embedding_text(self) -> str:
        parts = [self.title, self.section_path, self.text]
        return "\n".join(part for part in parts if part)


@dataclass(frozen=True)
class ChunkedDocument:
    doc_id: str
    raw_html: str
    title: str
    chunks: tuple[DocumentChunk, ...]


@dataclass(frozen=True)
class RawChunkBlock:
    section_path: str
    text: str


class StructuredHtmlChunkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._inside_body = False
        self._inside_title = False
        self._current_tag: str | None = None
        self._current_parts: list[str] = []
        self._title_parts: list[str] = []
        self._headings = {"h1": "", "h2": "", "h3": ""}
        self._blocks: list[RawChunkBlock] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in IGNORED_TAGS:
            self._ignored_depth += 1
            return

        if lowered == "body":
            self._inside_body = True
            return
        if lowered == "title":
            self._inside_title = True
            return
        if lowered == "br" and self._current_tag is not None:
            self._current_parts.append(" ")
            return

        if (
            self._ignored_depth == 0
            and self._inside_body
            and lowered in HEADING_TAGS.union(CHUNK_TAGS)
        ):
            self._flush_current()
            self._current_tag = lowered
            self._current_parts = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return

        if lowered == "body":
            self._flush_current()
            self._inside_body = False
            return
        if lowered == "title":
            self._inside_title = False
            return
        if lowered != self._current_tag:
            return

        self._flush_current()

    def _flush_current(self) -> None:
        if self._current_tag is None:
            return

        text = normalize_text("".join(self._current_parts))
        if text:
            if self._current_tag in HEADING_TAGS:
                self._headings[self._current_tag] = text
                if self._current_tag == "h1":
                    self._headings["h2"] = ""
                    self._headings["h3"] = ""
                elif self._current_tag == "h2":
                    self._headings["h3"] = ""
            else:
                section_path = " / ".join(
                    heading
                    for heading in (self._headings["h2"], self._headings["h3"])
                    if heading
                )
                self._blocks.append(RawChunkBlock(section_path=section_path, text=text))

        self._current_tag = None
        self._current_parts = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth > 0:
            return

        if self._inside_title:
            self._title_parts.append(data)
        if self._current_tag is not None:
            self._current_parts.append(data)

    def title(self) -> str:
        return normalize_text("".join(self._title_parts)) or self._headings["h1"]

    def blocks(self) -> tuple[RawChunkBlock, ...]:
        return tuple(self._blocks)


def chunk_html_document(
    doc_id: str,
    html: str,
    *,
    max_chunk_tokens: int = 384,
) -> ChunkedDocument:
    parsed = parse_document(html)
    title = parsed.title
    if not title:
        raise ValueError("Document title is empty after parsing.")
    if not parsed.visible_text:
        raise ValueError("Document body is empty after parsing.")

    parser = StructuredHtmlChunkParser()
    parser.feed(html)
    parser.close()

    raw_blocks = list(parser.blocks())
    if not raw_blocks:
        raw_blocks = [RawChunkBlock(section_path="", text=parsed.visible_text)]

    chunks = merge_blocks_into_chunks(
        doc_id=doc_id,
        title=title,
        raw_blocks=raw_blocks,
        max_chunk_tokens=max_chunk_tokens,
    )
    return ChunkedDocument(doc_id=doc_id, raw_html=html, title=title, chunks=chunks)


def merge_blocks_into_chunks(
    *,
    doc_id: str,
    title: str,
    raw_blocks: list[RawChunkBlock],
    max_chunk_tokens: int,
) -> tuple[DocumentChunk, ...]:
    chunks: list[DocumentChunk] = []
    current_section = ""
    current_parts: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current_section, current_parts, current_tokens
        if not current_parts:
            return
        merged_text = normalize_text(" ".join(current_parts))
        chunks.append(
            DocumentChunk(
                doc_id=doc_id,
                title=title,
                section_path=current_section,
                text=merged_text,
                ordinal=len(chunks),
                token_count=estimate_token_count(merged_text),
            )
        )
        current_section = ""
        current_parts = []
        current_tokens = 0

    for block in raw_blocks:
        block_tokens = estimate_token_count(block.text)
        section_changed = bool(current_parts) and block.section_path != current_section
        would_overflow = bool(current_parts) and current_tokens + block_tokens > max_chunk_tokens

        if section_changed or would_overflow:
            flush()

        if not current_parts:
            current_section = block.section_path

        current_parts.append(block.text)
        current_tokens += block_tokens

    flush()
    return tuple(chunks)


def estimate_token_count(text: str) -> int:
    return max(1, len(TOKEN_RE.findall(text)))
