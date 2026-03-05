# canvas_calibrator/rag/retriever.py
"""
Retrieve top-k chunks by cosine similarity using numpy.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from canvas_calibrator.rag.chunker import Chunk

log = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk: Chunk
    similarity_score: float


class Retriever:
    def __init__(self, embeddings: np.ndarray, chunks: list[Chunk], model_name: str = "all-MiniLM-L6-v2") -> None:
        self._embeddings = embeddings  # shape (N, D)
        self._chunks = chunks
        self._model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def retrieve(self, query: str, k: int = 8) -> list[RetrievedChunk]:
        """Return top-k chunks most similar to query."""
        model = self._get_model()
        query_vec = model.encode([query], convert_to_numpy=True)[0]  # shape (D,)

        # Cosine similarity: dot(A, b) / (|A| * |b|)
        norms = np.linalg.norm(self._embeddings, axis=1)
        query_norm = np.linalg.norm(query_vec)

        # Avoid division by zero
        safe_norms = np.where(norms == 0, 1e-9, norms)
        safe_query_norm = query_norm if query_norm > 0 else 1e-9

        scores = self._embeddings.dot(query_vec) / (safe_norms * safe_query_norm)

        top_k_idx = np.argsort(scores)[::-1][:k]
        return [
            RetrievedChunk(chunk=self._chunks[i], similarity_score=float(scores[i]))
            for i in top_k_idx
        ]
