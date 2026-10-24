"""Idempotent indexing: python -m app.ingest --file data/instruction_chunks.json  |  POST /ingest {version_id}."""
from __future__ import annotations

import argparse
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from app.core.chunks import load_chunks, slug, validate
from app.core.config import Settings
from app.core.registry import Registry
from app.search.dense import NumpyDense, QdrantDense
from app.search.index import LoadedIndex, build_lexical, load_chunks_dir, save_chunks
from app.search.tokenize import stemmer_name

log = logging.getLogger("ingest")


def make_embedder(cfg: Settings):  # noqa: ANN201
    """CPU bge-m3 embedder from llm_layer (None if dense is disabled or the package is unavailable)."""
    if not cfg.dense_enabled:
        return None
    try:
        from llm_layer.embeddings import Embedder
        return Embedder(model=cfg.emb_model)
    except Exception as e:  # noqa: BLE001
        log.warning("embedder unavailable, dense disabled: %s", e)
        return None


def build_index(cfg: Settings, raw: list[dict[str, Any]], embedder: Any = None) -> dict[str, Any]:
    """Validate → embed → (re)build Qdrant → write chunks → flip the active pointer. Old index stays live until the end."""
    v = validate(raw)
    chunks, report = v["indexable"], v["report"]
    label, sl = report["version"], slug(report["version"])
    vecs = embedder.embed([c["text"] for c in chunks]) if embedder is not None else None  # slow step first
    out = cfg.index_dir / sl
    save_chunks(out, chunks)
    if vecs is not None:
        np.save(out / "vectors.npy", vecs)
        if cfg.use_qdrant:
            QdrantDense.build(cfg.qdrant_path, f"chunks_{sl}", chunks, vecs)
    Registry(cfg.index_dir).activate(sl, label, len(chunks))
    report.update(dense=vecs is not None, stemmer=stemmer_name())
    log.info("indexed %s: %s", label, report)
    return report


def load_active(cfg: Settings) -> LoadedIndex | None:
    """Load the active version from disk (BM25 rebuilt, dense attached if present)."""
    reg = Registry(cfg.index_dir).read()
    if not reg["active"]:
        return None
    d = cfg.index_dir / reg["active"]
    chunks = load_chunks_dir(d)
    dense = None
    if cfg.dense_enabled:
        try:
            if cfg.use_qdrant and (Path(cfg.qdrant_path)).exists():
                q = QdrantDense(cfg.qdrant_path, f"chunks_{reg['active']}")
                dense = q if q.client.collection_exists(q.collection) else None
            if dense is None and (d / "vectors.npy").exists():
                dense = NumpyDense([c["id"] for c in chunks], np.load(d / "vectors.npy"), [c["access_level"] for c in chunks])
        except Exception as e:  # noqa: BLE001
            log.warning("dense index unavailable: %s", e)
    return build_lexical(chunks, cfg, dense)


def ingest_version(cfg: Settings, version_id: str, embedder: Any = None) -> dict[str, Any]:
    """PocketBase flow: status indexing → build → active (chunks_count, indexed_at) or failed (comment)."""
    from datetime import datetime, timezone
    from app.core.pb import PocketBase
    pb = PocketBase(cfg)
    rec = pb.get("document_versions", version_id)
    pb.patch("document_versions", version_id, {"status": "indexing"})
    try:
        if rec.get("file"):
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                f.write(pb.download(rec, "file"))
            raw = load_chunks(f.name)
        else:
            raw = load_chunks(cfg.data_file)
        report = build_index(cfg, raw, embedder)
        pb.patch("document_versions", version_id, {
            "status": "active", "chunks_count": report["indexed"], "comment": "",
            "indexed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000Z")})
        return report
    except Exception as e:  # noqa: BLE001
        pb.patch("document_versions", version_id, {"status": "failed", "comment": f"{type(e).__name__}: {e}"[:1000]})
        raise


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None)
    ap.add_argument("--no-dense", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    cfg = Settings()
    if a.no_dense:
        cfg.dense_enabled = False
    print(json.dumps(build_index(cfg, load_chunks(a.file or cfg.data_file), make_embedder(cfg)), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
