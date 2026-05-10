"""Split assistant replies so each chunk fits within MAX's 4000-char per-message limit.

Strategy (in order of preference):

1. If the whole message already fits, return it as a single chunk.
2. Greedy-pack paragraphs (separated by a blank line).
3. If a single paragraph is still too long, fall back to sentence packing
   ("." / "!" / "?" / "…" boundaries, also handles Russian quotes).
4. As a last resort, hard-cut on word boundaries, then on character boundaries.

This module is pure (no I/O) and easy to unit-test.
"""

from __future__ import annotations

import re
from typing import Iterable

# MAX hard-limit per docs.max.ru; we leave a small safety buffer for emoji
# expansion / surrogate pairs.
MAX_MESSAGE_LIMIT = 4000
SAFE_LIMIT = 3900

# Conservative sentence terminator — covers Latin and Cyrillic punctuation.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+")


def split_for_max(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    """Return a list of chunks, each ``len(chunk) <= limit``.

    The function never raises. An empty / whitespace-only input yields an
    empty list so the caller can decide whether to suppress the message
    entirely.
    """
    if text is None:
        return []
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    for paragraph in _split_paragraphs(text):
        if not paragraph.strip():
            continue
        if len(paragraph) <= limit:
            _append_or_pack(chunks, paragraph, limit)
            continue
        for sentence in _split_sentences(paragraph):
            if len(sentence) <= limit:
                _append_or_pack(chunks, sentence, limit)
                continue
            for piece in _hard_split(sentence, limit):
                _append_or_pack(chunks, piece, limit)
    return chunks


def _split_paragraphs(text: str) -> Iterable[str]:
    return [p for p in re.split(r"\n{2,}", text) if p.strip()]


def _split_sentences(paragraph: str) -> Iterable[str]:
    parts = [p for p in _SENTENCE_BOUNDARY.split(paragraph) if p.strip()]
    return parts or [paragraph]


def _hard_split(text: str, limit: int) -> Iterable[str]:
    """Last-resort: split a single oversized run preferring word boundaries."""
    out: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        out.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if remaining:
        out.append(remaining)
    return out


def _append_or_pack(chunks: list[str], piece: str, limit: int) -> None:
    """Greedy-pack ``piece`` into the trailing chunk while it still fits.

    Keeps separator semantics: paragraphs are joined with "\n\n", everything
    else uses a single space.
    """
    piece = piece.strip()
    if not piece:
        return
    if not chunks:
        chunks.append(piece)
        return
    last = chunks[-1]
    candidate = f"{last}\n\n{piece}"
    if len(candidate) <= limit:
        chunks[-1] = candidate
        return
    candidate = f"{last} {piece}"
    if len(candidate) <= limit:
        chunks[-1] = candidate
        return
    chunks.append(piece)
