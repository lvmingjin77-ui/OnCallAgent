from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np


DEFAULT_BGE_MODEL_REPO = "BAAI/bge-base-zh-v1.5"
DEFAULT_LOCAL_MODEL_RELATIVE_PATH = Path(".local_models") / "bge-base-zh-v1.5"
DEFAULT_BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def resolve_default_bge_model_name(base_dir: Path) -> str:
    local_model_dir = base_dir / DEFAULT_LOCAL_MODEL_RELATIVE_PATH
    if local_model_dir.exists():
        return str(local_model_dir)
    return DEFAULT_BGE_MODEL_REPO


class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str:
        ...

    @property
    def backend_name(self) -> str:
        ...

    @property
    def embedding_dim(self) -> int | None:
        ...

    def embed_queries(self, queries: list[str]) -> np.ndarray:
        ...

    def embed_passages(self, passages: list[str]) -> np.ndarray:
        ...


class EmbeddingProviderUnavailableError(RuntimeError):
    pass


@dataclass
class LocalBGEEmbeddingProvider:
    model_name: str = DEFAULT_BGE_MODEL_REPO
    device: str = "cpu"
    batch_size: int = 32
    query_instruction: str = DEFAULT_BGE_QUERY_INSTRUCTION
    cache_dir: str | None = None
    local_files_only: bool = False
    trust_remote_code: bool = False

    def __post_init__(self) -> None:
        self._model = None
        self._embedding_dim: int | None = None

    @property
    def backend_name(self) -> str:
        return "sentence-transformers"

    @property
    def embedding_dim(self) -> int | None:
        return self._embedding_dim

    def embed_queries(self, queries: list[str]) -> np.ndarray:
        prefixed_queries = [
            f"{self.query_instruction}{query}" if query else self.query_instruction
            for query in queries
        ]
        return self._encode(prefixed_queries)

    def embed_passages(self, passages: list[str]) -> np.ndarray:
        return self._encode(passages)

    def _encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            dim = self._embedding_dim or 0
            return np.zeros((0, dim), dtype=np.float32)

        model = self._ensure_model()
        vectors = model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        embeddings = np.asarray(vectors, dtype=np.float32)
        if embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)
        self._embedding_dim = int(embeddings.shape[1])
        return embeddings

    def _ensure_model(self):
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingProviderUnavailableError(
                "Phase 2 requires local embedding dependencies. "
                "Install 'sentence-transformers' and 'torch' first."
            ) from exc

        try:
            self._model = SentenceTransformer(
                self.model_name,
                device=self.device,
                cache_folder=self.cache_dir,
                trust_remote_code=self.trust_remote_code,
                local_files_only=self.local_files_only,
            )
        except Exception as exc:  # pragma: no cover - exercised in runtime environments
            raise EmbeddingProviderUnavailableError(
                f"Unable to load local embedding model '{self.model_name}'."
            ) from exc

        get_dimension = getattr(self._model, "get_sentence_embedding_dimension", None)
        if callable(get_dimension):
            self._embedding_dim = int(get_dimension())
        return self._model
