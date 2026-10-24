"""Shared fixtures: a 20-chunk subset of the real data file (+ a few explicit points), a toy embedder."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from app.core.chunks import load_chunks
from app.core.config import Settings
from app.search.anchors import load_anchors
from app.search.dense import NumpyDense
from app.search.hybrid import Searcher
from app.search.index import build_lexical

ROOT = Path(__file__).resolve().parents[1]
EXTRA_IDS = {"6.4", "10.3", "10.6", "10.11", "5.6"}


def subset() -> list[dict]:
    """First 20 real chunks (includes the virtual 1.4 and its parts 1.4#1/#2) plus EXTRA_IDS."""
    data = load_chunks(ROOT / "data/instruction_chunks.json")
    return data[:20] + [c for c in data[20:] if c["id"] in EXTRA_IDS]


class ToyEmbedder:
    """Deterministic hashed bag-of-words embedder (no model download) with the Embedder interface."""
    dim = 256

    def embed(self, texts):  # noqa: ANN001, ANN201
        out = np.zeros((len(texts), self.dim), np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"\w+", t.lower()):
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)

    def embed_query(self, text: str):  # noqa: ANN201
        return self.embed([text])[0]


def make_searcher(chunks: list[dict], tmp: Path, dense: bool = False) -> Searcher:
    cfg = Settings(index_dir=tmp / "idx", qdrant_path=str(tmp / "q"), use_qdrant=False,
                   anchors_file=str(ROOT / "anchors.yaml"))
    chunks = [c for c in chunks if not c.get("virtual")]
    d = None
    emb = None
    if dense:
        emb = ToyEmbedder()
        d = NumpyDense([c["id"] for c in chunks], emb.embed([c["text"] for c in chunks]), [c["access_level"] for c in chunks])
    return Searcher(cfg, build_lexical(chunks, cfg, d), emb, None, load_anchors(cfg.anchors_file))
