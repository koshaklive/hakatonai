"""Small self-contained BM25 (Okapi) with an inverted index; ~400 chunks, so numpy is plenty."""
from __future__ import annotations

import math
from collections import Counter

import numpy as np


class BM25:
    """BM25 over pre-tokenised documents."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b, self.n = k1, b, len(docs)
        self.dl = np.array([len(d) for d in docs], dtype=np.float32)
        self.avgdl = float(self.dl.mean()) if self.n else 0.0
        self.post: dict[str, list[tuple[int, int]]] = {}
        for i, d in enumerate(docs):
            for t, f in Counter(d).items():
                self.post.setdefault(t, []).append((i, f))
        self.idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.post.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        """Raw BM25 score for every document."""
        s = np.zeros(self.n, dtype=np.float32)
        for t in set(query):
            for i, f in self.post.get(t, ()):
                s[i] += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.dl[i] / self.avgdl))
        return s

    def upper_bound(self, query: list[str]) -> float:
        """Loose max achievable score (sum idf·(k1+1)); used to normalise scores to 0..1."""
        return float(sum(self.idf.get(t, 0.0) * (self.k1 + 1) for t in set(query))) or 1.0
