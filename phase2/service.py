from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from phase1.engine import SearchHit
from phase1.parsing import normalize_text

from .chunking import ChunkedDocument, DocumentChunk, chunk_html_document
from .embedder import EmbeddingProvider, EmbeddingProviderUnavailableError
from .index_store import (
    SCHEMA_VERSION,
    IndexedDocument,
    IndexManifest,
    IndexStore,
    LoadedIndex,
)


class SemanticSearchUnavailableError(RuntimeError):
    pass


class IndexNotReadyError(SemanticSearchUnavailableError):
    pass


class SemanticSearchService:
    def is_available(self) -> bool:
        raise NotImplementedError

    def status_message(self) -> str | None:
        raise NotImplementedError

    def search(self, query: str) -> list[SearchHit]:
        raise NotImplementedError

    def get_document(self, doc_id: str):
        raise NotImplementedError

    def upsert_document(self, doc_id: str, html: str) -> None:
        raise NotImplementedError


class DisabledSemanticSearchService(SemanticSearchService):
    def __init__(self, message: str) -> None:
        self._message = message

    def is_available(self) -> bool:
        return False

    def status_message(self) -> str | None:
        return self._message

    def search(self, query: str) -> list[SearchHit]:
        raise IndexNotReadyError(self._message)

    def get_document(self, doc_id: str):
        return None

    def upsert_document(self, doc_id: str, html: str) -> None:
        return None


@dataclass(frozen=True)
class RankedChunk:
    score: float
    chunk: DocumentChunk


class LocalSemanticSearchService(SemanticSearchService):
    def __init__(
        self,
        *,
        index_dir: Path,
        provider: EmbeddingProvider,
    ) -> None:
        self._provider = provider
        self._store = IndexStore(index_dir)
        self._index = self._store.load()
        self._documents_by_id = self._index.documents_by_id()

    def is_available(self) -> bool:
        return True

    def status_message(self) -> str | None:
        return None

    def search(self, query: str) -> list[SearchHit]:
        normalized_query = normalize_text(query)
        if not normalized_query:
            return []

        try:
            query_embedding = self._provider.embed_queries([normalized_query])
        except EmbeddingProviderUnavailableError as exc:
            raise SemanticSearchUnavailableError(str(exc)) from exc
        if query_embedding.size == 0:
            return []

        query_vector = l2_normalize(query_embedding)[0]
        scores = cosine_similarity_scores(self._index.embeddings, query_vector)
        if scores.size == 0:
            return []

        best_by_doc: dict[str, RankedChunk] = {}
        for chunk, score in zip(self._index.chunks, scores):
            ranked_chunk = RankedChunk(score=float(score), chunk=chunk)
            existing = best_by_doc.get(chunk.doc_id)
            if existing is None or ranked_chunk.score > existing.score:
                best_by_doc[chunk.doc_id] = ranked_chunk

        ranked_hits: list[tuple[float, SearchHit]] = []
        for doc_id, ranked_chunk in best_by_doc.items():
            document = self._documents_by_id[doc_id]
            ranked_hits.append(
                (
                    ranked_chunk.score,
                    SearchHit(
                        id=document.id,
                        title=document.title,
                        snippet=build_snippet(ranked_chunk.chunk.text),
                        score=round(cosine_to_score(ranked_chunk.score), 4),
                    ),
                )
            )

        ranked_hits.sort(key=lambda item: (-item[0], item[1].id))
        return [hit for _, hit in ranked_hits]

    def get_document(self, doc_id: str) -> IndexedDocument | None:
        return self._documents_by_id.get(doc_id)

    def upsert_document(self, doc_id: str, html: str) -> None:
        chunked_document = chunk_html_document(doc_id, html)
        try:
            new_embeddings = self._provider.embed_passages(
                [chunk.embedding_text for chunk in chunked_document.chunks]
            )
        except EmbeddingProviderUnavailableError as exc:
            raise SemanticSearchUnavailableError(str(exc)) from exc

        documents_by_id = self._index.documents_by_id()
        documents_by_id[doc_id] = indexed_document_from_chunked_document(chunked_document)

        chunks_by_doc, embeddings_by_doc = split_index_by_document(self._index)
        chunks_by_doc[doc_id] = list(chunked_document.chunks)
        embeddings_by_doc[doc_id] = l2_normalize(new_embeddings)

        rebuilt_index = assemble_loaded_index(
            documents_by_id=documents_by_id,
            chunks_by_doc=chunks_by_doc,
            embeddings_by_doc=embeddings_by_doc,
            model_name=self._provider.model_name,
            backend_name=self._provider.backend_name,
            embedding_dim=embedding_dimension(new_embeddings, self._provider.embedding_dim),
        )
        persist_loaded_index(self._store, rebuilt_index)
        self._index = rebuilt_index
        self._documents_by_id = rebuilt_index.documents_by_id()


def build_loaded_index(
    *,
    chunked_documents: list[ChunkedDocument],
    passage_embeddings: np.ndarray,
    model_name: str,
    backend_name: str,
    embedding_dim: int,
) -> LoadedIndex:
    normalized_embeddings = l2_normalize(passage_embeddings)
    chunks: list[DocumentChunk] = []
    documents: list[IndexedDocument] = []
    offset = 0

    for chunked_document in sorted(chunked_documents, key=lambda document: document.doc_id):
        documents.append(indexed_document_from_chunked_document(chunked_document))
        for chunk in chunked_document.chunks:
            chunks.append(chunk)
            offset += 1

    if normalized_embeddings.shape[0] != len(chunks):
        raise ValueError("Embedding row count does not match generated chunks.")

    manifest = IndexManifest(
        schema_version=SCHEMA_VERSION,
        embedding_model=model_name,
        embedding_backend=backend_name,
        embedding_dim=embedding_dim,
        document_count=len(documents),
        chunk_count=len(chunks),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return LoadedIndex(
        manifest=manifest,
        documents=tuple(documents),
        chunks=tuple(chunks),
        embeddings=normalized_embeddings,
    )


def persist_loaded_index(store: IndexStore, loaded_index: LoadedIndex) -> None:
    store.save_atomic(
        manifest=loaded_index.manifest,
        documents=loaded_index.documents,
        chunks=loaded_index.chunks,
        embeddings=loaded_index.embeddings,
    )


def assemble_loaded_index(
    *,
    documents_by_id: dict[str, IndexedDocument],
    chunks_by_doc: dict[str, list[DocumentChunk]],
    embeddings_by_doc: dict[str, np.ndarray],
    model_name: str,
    backend_name: str,
    embedding_dim: int,
) -> LoadedIndex:
    ordered_doc_ids = sorted(documents_by_id)
    ordered_documents = [documents_by_id[doc_id] for doc_id in ordered_doc_ids]
    ordered_chunks: list[DocumentChunk] = []
    ordered_embedding_rows: list[np.ndarray] = []

    for doc_id in ordered_doc_ids:
        doc_chunks = chunks_by_doc.get(doc_id, [])
        doc_embeddings = embeddings_by_doc.get(doc_id)
        if doc_embeddings is None:
            raise ValueError(f"Missing embeddings for document '{doc_id}'.")
        if doc_embeddings.shape[0] != len(doc_chunks):
            raise ValueError(f"Chunk and embedding counts mismatch for document '{doc_id}'.")

        ordered_chunks.extend(doc_chunks)
        ordered_embedding_rows.extend(doc_embeddings)

    if ordered_embedding_rows:
        embedding_matrix = np.vstack(ordered_embedding_rows).astype(np.float32)
    else:
        embedding_matrix = np.zeros((0, embedding_dim), dtype=np.float32)

    manifest = IndexManifest(
        schema_version=SCHEMA_VERSION,
        embedding_model=model_name,
        embedding_backend=backend_name,
        embedding_dim=embedding_dim,
        document_count=len(ordered_documents),
        chunk_count=len(ordered_chunks),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return LoadedIndex(
        manifest=manifest,
        documents=tuple(ordered_documents),
        chunks=tuple(ordered_chunks),
        embeddings=embedding_matrix,
    )


def split_index_by_document(
    loaded_index: LoadedIndex,
) -> tuple[dict[str, list[DocumentChunk]], dict[str, np.ndarray]]:
    chunks_by_doc: dict[str, list[DocumentChunk]] = {}
    embedding_rows_by_doc: dict[str, list[np.ndarray]] = {}
    for chunk, embedding in zip(loaded_index.chunks, loaded_index.embeddings):
        chunks_by_doc.setdefault(chunk.doc_id, []).append(chunk)
        embedding_rows_by_doc.setdefault(chunk.doc_id, []).append(embedding)

    embeddings_by_doc = {
        doc_id: np.vstack(rows).astype(np.float32)
        for doc_id, rows in embedding_rows_by_doc.items()
    }
    return chunks_by_doc, embeddings_by_doc


def indexed_document_from_chunked_document(chunked_document: ChunkedDocument) -> IndexedDocument:
    return IndexedDocument(
        id=chunked_document.doc_id,
        title=chunked_document.title,
        raw_html=chunked_document.raw_html,
        chunk_count=len(chunked_document.chunks),
    )


def build_snippet(text: str, limit: int = 160) -> str:
    normalized = normalize_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def l2_normalize(embeddings: np.ndarray) -> np.ndarray:
    array = np.asarray(embeddings, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.size == 0:
        return array
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    safe_norms = np.maximum(norms, 1e-12)
    return array / safe_norms


def cosine_similarity_scores(embeddings: np.ndarray, query_vector: np.ndarray) -> np.ndarray:
    matrix = np.asarray(embeddings, dtype=np.float64)
    vector = np.asarray(query_vector, dtype=np.float64)
    if matrix.ndim != 2:
        raise ValueError("Embeddings must be a 2D matrix.")
    if vector.ndim != 1:
        raise ValueError("Query embedding must be a 1D vector.")
    if matrix.shape[1] != vector.shape[0]:
        raise ValueError("Embedding dimension mismatch between index and query vector.")
    return np.sum(matrix * vector, axis=1, dtype=np.float64).astype(np.float32)


def cosine_to_score(cosine_similarity: float) -> float:
    return max(0.0, min(1.0, (cosine_similarity + 1.0) / 2.0))


def embedding_dimension(embeddings: np.ndarray, fallback_dimension: int | None) -> int:
    if embeddings.ndim == 2 and embeddings.shape[1] > 0:
        return int(embeddings.shape[1])
    return int(fallback_dimension or 0)
