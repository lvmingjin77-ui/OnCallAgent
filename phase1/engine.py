from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from threading import RLock
from typing import Iterable

from .parsing import parse_document, normalize_for_search


DOCUMENT_ID_SUFFIX_RE = re.compile(r"^(.*?)(\d+)$")


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    raw_html: str
    title: str
    visible_text: str
    normalized_title: str
    normalized_text: str


@dataclass(frozen=True)
class SearchHit:
    id: str
    title: str
    snippet: str
    score: float


class SearchEngine:
    def __init__(self) -> None:
        self._documents: dict[str, DocumentRecord] = {}
        self._lock = RLock()

    def upsert_document(self, doc_id: str, html: str) -> tuple[DocumentRecord, bool]:
        parsed = parse_document(html)
        if not parsed.title:
            raise ValueError("Document title is empty after parsing.")
        if not parsed.visible_text:
            raise ValueError("Document body is empty after parsing.")

        record = DocumentRecord(
            id=doc_id,
            raw_html=html,
            title=parsed.title,
            visible_text=parsed.visible_text,
            normalized_title=parsed.normalized_title,
            normalized_text=parsed.normalized_text,
        )

        with self._lock:
            created = doc_id not in self._documents
            self._documents[doc_id] = record
            return record, created

    def load_directory(self, data_dir: Path) -> None:
        for path in sorted(data_dir.glob("*.html")):
            self.upsert_document(path.stem, path.read_text(encoding="utf-8"))

    def search(self, query: str) -> list[SearchHit]:
        normalized_query = normalize_for_search(query)
        if not normalized_query:
            return []

        terms = normalized_query.split()
        if not terms:
            return []

        with self._lock:
            results = [self._match_document(doc, terms) for doc in self._documents.values()]

        hits = [hit for hit in results if hit is not None]
        hits.sort(key=search_hit_sort_key)
        return hits

    def documents(self) -> Iterable[DocumentRecord]:
        with self._lock:
            return tuple(self._documents.values())

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        with self._lock:
            return self._documents.get(doc_id)

    def _match_document(
        self, document: DocumentRecord, terms: list[str]
    ) -> SearchHit | None:
        body_counts = []
        body_offsets = []

        for term in terms:
            body_count = document.normalized_text.count(term)
            if body_count == 0:
                return None

            body_counts.append(body_count)

            body_offset = document.normalized_text.find(term)
            if body_offset >= 0:
                body_offsets.append(body_offset)

        body_match_offset = min(body_offsets, default=-1)
        snippet = build_snippet(document.visible_text, body_match_offset, max(terms, key=len))

        position_bonus = 0.0
        if body_match_offset >= 0:
            position_bonus = 1.0 / (1.0 + body_match_offset)
        score = (
            1.0 * sum(body_counts)
            + position_bonus
        )
        return SearchHit(
            id=document.id,
            title=document.title,
            snippet=snippet,
            score=round(score, 4),
        )


def build_snippet(text: str, first_offset: int, emphasis: str, radius: int = 72) -> str:
    if not text:
        return ""

    if first_offset < 0:
        end = min(len(text), radius * 2)
        snippet = text[:end].strip()
        return snippet

    start = max(0, first_offset - radius)
    end = min(len(text), first_offset + len(emphasis) + radius)
    snippet = text[start:end].strip()

    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def search_hit_sort_key(hit: SearchHit) -> tuple[float, str, int, str]:
    match = DOCUMENT_ID_SUFFIX_RE.match(hit.id)
    if match:
        prefix, suffix = match.groups()
        return (-hit.score, prefix, int(suffix), hit.id)
    return (-hit.score, hit.id, -1, hit.id)
