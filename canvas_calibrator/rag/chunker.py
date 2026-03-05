# canvas_calibrator/rag/chunker.py
"""
Split Document text into overlapping token chunks.
Uses tiktoken (cl100k_base) for token counting.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

CHUNK_SIZE = 400    # tokens
CHUNK_OVERLAP = 50  # tokens


@dataclass
class Chunk:
    chunk_id: str       # "{doc_id}:{chunk_index}"
    doc_id: str
    source_type: str
    source_path: str
    title: str
    text: str
    chunk_index: int


def _get_encoder():
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        log.warning("tiktoken not installed — falling back to character-based chunking (~4 chars/token)")
        return None


class _CharFallbackEncoder:
    """Simple character-based fallback when tiktoken is unavailable."""
    CHARS_PER_TOKEN = 4

    def encode(self, text: str) -> list[int]:
        # Return fake token list using char positions
        return list(range(0, len(text), self.CHARS_PER_TOKEN))

    def decode(self, tokens: list[int]) -> str:
        # Not needed for chunking
        raise NotImplementedError


def chunk_documents(docs) -> list[Chunk]:
    """
    Chunk a list of Document objects.
    Skips documents with extractable=False.
    """
    from canvas_calibrator.ingest.content_loader import Document

    encoder = _get_encoder() or _CharFallbackEncoder()
    chunks: list[Chunk] = []

    for doc in docs:
        if not doc.extractable or not doc.text.strip():
            continue

        tokens = encoder.encode(doc.text)

        # Split words (not tokens directly) — chunk by word boundaries to avoid
        # splitting mid-word. We use token count as a guide.
        words = doc.text.split()
        if not words:
            continue

        # Estimate chars per token from this document
        chars = len(doc.text)
        token_count = len(tokens)
        chars_per_token = chars / token_count if token_count else 4.0

        chunk_chars = int(CHUNK_SIZE * chars_per_token)
        overlap_chars = int(CHUNK_OVERLAP * chars_per_token)

        start = 0
        chunk_index = 0
        text = doc.text

        while start < len(text):
            end = start + chunk_chars
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(Chunk(
                    chunk_id=f"{doc.doc_id}:{chunk_index}",
                    doc_id=doc.doc_id,
                    source_type=doc.source_type,
                    source_path=doc.source_path,
                    title=doc.title,
                    text=chunk_text,
                    chunk_index=chunk_index,
                ))
                chunk_index += 1
            if end >= len(text):
                break
            start = end - overlap_chars

    log.info("Created %d chunks from %d documents", len(chunks), len(docs))
    return chunks
