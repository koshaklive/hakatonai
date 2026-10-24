"""Search query normalization shared by retrieval and intent handling."""
from __future__ import annotations

import re
from typing import Any

from app.search.tokenize import tokenize

_MESSENGER_HEADER = re.compile(
    r"(?im)^\s*[A-ZА-ЯЁ][\wА-Яа-яЁё.@ -]{0,40}\s+[—–-]\s*\d{1,2}:\d{2}\s*(?:\r?\n|$)"
)
_INTRODUCTIONS = re.compile(
    r"\b(?:отформатируй|по\s+правилам\s+инструкции|подскажи|а\s+правда\s+ли)\b[,:]?\s*",
    re.I,
)
_SPACE = re.compile(r"\s+")


def normalize_query(query: str) -> str:
    """Remove copied chat headers and conversational lead-ins from a search query."""
    normalized = _MESSENGER_HEADER.sub("", query)
    normalized = _INTRODUCTIONS.sub("", normalized)
    return _SPACE.sub(" ", normalized).strip(" \t\r\n—–-")


def query_evidence(query: str, hits: list[Any], abbrevs: set[str] | frozenset[str]) -> tuple[float, float, float]:
    """Return the strongest dense, BM25 and token-overlap evidence among retrieved hits."""
    query_tokens = set(tokenize(normalize_query(query), abbrevs))
    dense = max((float(hit.scores.get("dense", 0.0)) for hit in hits), default=0.0)
    bm25 = max((float(hit.scores.get("bm25n", 0.0)) for hit in hits), default=0.0)
    overlap = max(
        (len(query_tokens & set(tokenize(hit.text, abbrevs))) / len(query_tokens) for hit in hits if query_tokens),
        default=0.0,
    )
    return dense, bm25, overlap


def passes_hybrid_filter(dense: float, bm25: float, overlap: float, *,
                         dense_min: float, bm25_min: float, overlap_min: float) -> bool:
    """Pass a result if either semantic or lexical evidence reaches its threshold."""
    return dense >= dense_min or bm25 >= bm25_min or overlap >= overlap_min
