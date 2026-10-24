"""CPU embeddings (bge-m3) with batching and on-disk cache; optional bge-reranker-v2-m3."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Sequence

import numpy as np
from dotenv import load_dotenv

load_dotenv()


class Embedder:
    """sentence-transformers wrapper; vectors are L2-normalised float32, cached in SQLite."""

    def __init__(self, model: str | None = None, device: str | None = None,
                 batch_size: int | None = None, cache_dir: str | None = None) -> None:
        self.model_name = model or os.getenv("EMB_MODEL", "BAAI/bge-m3")
        self.device = device or os.getenv("EMB_DEVICE", "cpu")
        self.batch_size = batch_size or int(os.getenv("EMB_BATCH", "16"))
        d = Path(cache_dir or os.getenv("EMB_CACHE_DIR", ".cache/emb"))
        d.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(d / "emb.sqlite", check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS e (k TEXT PRIMARY KEY, v BLOB)")
        self._model = None

    @property
    def model(self):  # lazy load
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model_name}\0{text}".encode()).hexdigest()

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Embed texts → (n, dim) float32; only uncached texts hit the model."""
        keys = [self._key(t) for t in texts]
        found = {k: np.frombuffer(v, dtype=np.float32) for k, v in self._db.execute(
            f"SELECT k, v FROM e WHERE k IN ({','.join('?' * len(keys))})", keys)} if keys else {}
        todo = [(k, t) for k, t in dict(zip(keys, texts)).items() if k not in found]
        if todo:
            vecs = self.model.encode([t for _, t in todo], batch_size=self.batch_size,
                                     normalize_embeddings=True, show_progress_bar=False).astype(np.float32)
            with self._db:
                self._db.executemany("INSERT OR REPLACE INTO e VALUES (?, ?)",
                                     [(k, v.tobytes()) for (k, _), v in zip(todo, vecs)])
            found.update({k: v for (k, _), v in zip(todo, vecs)})
        return np.stack([found[k] for k in keys]) if keys else np.zeros((0, 0), np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed one query → (dim,)."""
        return self.embed([text])[0]


class Reranker:
    """Optional cross-encoder reranker on CPU."""

    def __init__(self, model: str | None = None, device: str | None = None) -> None:
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model or os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
                                  device=device or os.getenv("EMB_DEVICE", "cpu"))

    def rerank(self, query: str, docs: Sequence[str], top_k: int = 5) -> list[tuple[int, float]]:
        """Return [(doc_index, score)] sorted by score desc, length ≤ top_k."""
        scores = self.model.predict([(query, d) for d in docs], batch_size=8)
        return sorted(enumerate(map(float, scores)), key=lambda x: -x[1])[:top_k]
