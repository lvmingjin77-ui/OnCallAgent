from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
from typing import Iterable
from uuid import uuid4

import numpy as np

from .chunking import DocumentChunk


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IndexedDocument:
    id: str
    title: str
    raw_html: str
    chunk_count: int


@dataclass(frozen=True)
class IndexManifest:
    schema_version: int
    embedding_model: str
    embedding_backend: str
    embedding_dim: int
    document_count: int
    chunk_count: int
    created_at: str


@dataclass(frozen=True)
class LoadedIndex:
    manifest: IndexManifest
    documents: tuple[IndexedDocument, ...]
    chunks: tuple[DocumentChunk, ...]
    embeddings: np.ndarray

    def documents_by_id(self) -> dict[str, IndexedDocument]:
        return {document.id: document for document in self.documents}


class IndexStore:
    def __init__(self, index_dir: Path) -> None:
        self.index_dir = index_dir

    @property
    def manifest_path(self) -> Path:
        return self.index_dir / "manifest.json"

    @property
    def documents_path(self) -> Path:
        return self.index_dir / "documents.jsonl"

    @property
    def chunks_path(self) -> Path:
        return self.index_dir / "chunks.jsonl"

    @property
    def embeddings_path(self) -> Path:
        return self.index_dir / "embeddings.npy"

    def exists(self) -> bool:
        return (
            self.manifest_path.exists()
            and self.documents_path.exists()
            and self.chunks_path.exists()
            and self.embeddings_path.exists()
        )

    def load(self) -> LoadedIndex:
        if not self.exists():
            raise FileNotFoundError(
                f"Semantic index not found under '{self.index_dir}'. "
                "Run `python3 -m phase2.rebuild_index` first."
            )

        manifest_payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest = IndexManifest(**manifest_payload)

        documents = tuple(
            IndexedDocument(**json.loads(line))
            for line in self.documents_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        chunks = tuple(
            DocumentChunk(**json.loads(line))
            for line in self.chunks_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        embeddings = np.load(self.embeddings_path)
        if embeddings.dtype != np.float32:
            embeddings = embeddings.astype(np.float32)
        if embeddings.shape[0] != len(chunks):
            raise ValueError("Embedding row count does not match stored chunks.")

        return LoadedIndex(
            manifest=manifest,
            documents=documents,
            chunks=chunks,
            embeddings=embeddings,
        )

    def save_atomic(
        self,
        *,
        manifest: IndexManifest,
        documents: Iterable[IndexedDocument],
        chunks: Iterable[DocumentChunk],
        embeddings: np.ndarray,
    ) -> None:
        embeddings_array = np.asarray(embeddings, dtype=np.float32)
        documents_tuple = tuple(documents)
        chunks_tuple = tuple(chunks)
        if embeddings_array.ndim != 2:
            raise ValueError("Embeddings must be a 2D array.")
        if embeddings_array.shape[0] != len(chunks_tuple):
            raise ValueError("Embedding row count must match chunk count.")

        temp_dir = self.index_dir.parent / f".{self.index_dir.name}.tmp-{uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=False)
        try:
            (temp_dir / "manifest.json").write_text(
                json.dumps(asdict(manifest), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            write_jsonl(temp_dir / "documents.jsonl", documents_tuple)
            write_jsonl(temp_dir / "chunks.jsonl", chunks_tuple)
            np.save(temp_dir / "embeddings.npy", embeddings_array)

            if self.index_dir.exists():
                shutil.rmtree(self.index_dir)
            temp_dir.rename(self.index_dir)
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise


def write_jsonl(path: Path, rows: Iterable[object]) -> None:
    lines = [json.dumps(asdict(row), ensure_ascii=False) for row in rows]
    payload = "\n".join(lines)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")
