# canvas_calibrator/rag/embedder.py
"""
Embed chunks using sentence-transformers all-MiniLM-L6-v2.
Caches embeddings to .cache/{course_id}_embeddings.npz.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from canvas_calibrator.rag.chunker import Chunk

log = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"


def _cache_path(cache_dir: Path, course_id: str | int) -> Path:
    return cache_dir / f"{course_id}_embeddings.npz"


def embed_chunks(
    chunks: list[Chunk],
    course_id: str | int,
    cache_dir: Path,
    rebuild: bool = False,
) -> tuple[np.ndarray, list[Chunk]]:
    """
    Embed chunks and cache results.

    Returns:
        (embeddings, chunks) where embeddings[i] corresponds to chunks[i].
        Shape: (N, embedding_dim)
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(cache_dir, course_id)
    meta_file = cache_file.with_suffix(".pkl")

    if not rebuild and cache_file.exists() and meta_file.exists():
        log.info("Loading cached embeddings from %s", cache_file)
        data = np.load(cache_file)
        embeddings = data["embeddings"]
        with open(meta_file, "rb") as f:
            cached_chunks = pickle.load(f)
        if len(cached_chunks) == len(chunks) and len(embeddings) == len(chunks):
            log.info("Cache hit: %d embeddings", len(embeddings))
            return embeddings, cached_chunks
        log.info("Cache mismatch — rebuilding embeddings")

    log.info("Embedding %d chunks with %s", len(chunks), MODEL_NAME)

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "sentence-transformers is required. Install with: pip install sentence-transformers"
        )

    model = SentenceTransformer(MODEL_NAME)
    texts = [c.text for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)

    np.savez_compressed(cache_file, embeddings=embeddings)
    with open(meta_file, "wb") as f:
        pickle.dump(chunks, f)

    log.info("Saved embeddings to %s", cache_file)
    return embeddings, chunks
