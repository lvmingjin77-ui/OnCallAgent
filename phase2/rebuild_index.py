from __future__ import annotations

import os
from pathlib import Path

from .chunking import chunk_html_document
from .embedder import (
    DEFAULT_BGE_MODEL_REPO,
    LocalBGEEmbeddingProvider,
    resolve_default_bge_model_name,
)
from .service import (
    build_loaded_index,
    embedding_dimension,
    persist_loaded_index,
)
from .index_store import IndexStore


def rebuild_semantic_index(
    *,
    data_dir: Path,
    index_dir: Path,
    provider,
) -> None:
    chunked_documents = [
        chunk_html_document(path.stem, path.read_text(encoding="utf-8"))
        for path in sorted(data_dir.glob("*.html"))
    ]
    passages = [
        chunk.embedding_text
        for document in chunked_documents
        for chunk in document.chunks
    ]
    passage_embeddings = provider.embed_passages(passages)
    loaded_index = build_loaded_index(
        chunked_documents=chunked_documents,
        passage_embeddings=passage_embeddings,
        model_name=provider.model_name,
        backend_name=provider.backend_name,
        embedding_dim=embedding_dimension(
            passage_embeddings, provider.embedding_dim
        ),
    )
    persist_loaded_index(IndexStore(index_dir), loaded_index)


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]
    data_dir = base_dir / "data"
    index_dir = Path(os.environ.get("PHASE2_INDEX_DIR", str(base_dir / ".phase2_index")))
    model_name = os.environ.get("PHASE2_MODEL_NAME", resolve_default_bge_model_name(base_dir))
    device = os.environ.get("PHASE2_DEVICE", "cpu")
    batch_size = int(os.environ.get("PHASE2_BATCH_SIZE", "32"))
    local_files_only_default = (
        "1" if model_name != DEFAULT_BGE_MODEL_REPO and Path(model_name).exists() else "0"
    )

    provider = LocalBGEEmbeddingProvider(
        model_name=model_name,
        device=device,
        batch_size=batch_size,
        local_files_only=os.environ.get("PHASE2_LOCAL_FILES_ONLY", local_files_only_default)
        == "1",
    )
    rebuild_semantic_index(data_dir=data_dir, index_dir=index_dir, provider=provider)
    print(f"Rebuilt Phase 2 semantic index at {index_dir}")


if __name__ == "__main__":
    main()
