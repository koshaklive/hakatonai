"""Configuration: every threshold, path and flag comes from .env (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _b(key: str, default: str) -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Runtime settings (read once from the environment)."""
    data_file: str = field(default_factory=lambda: os.getenv("DATA_FILE", "data/instruction_chunks.json"))
    index_dir: Path = field(default_factory=lambda: Path(os.getenv("INDEX_DIR", "indexes")))
    qdrant_path: str = field(default_factory=lambda: os.getenv("QDRANT_PATH", "./qdrant_data"))
    dense_enabled: bool = field(default_factory=lambda: _b("DENSE", "1"))
    use_qdrant: bool = field(default_factory=lambda: _b("USE_QDRANT", "1"))
    rerank: bool = field(default_factory=lambda: _b("RERANK", "0"))
    # retrieval sizes
    dense_k: int = field(default_factory=lambda: int(os.getenv("DENSE_K", "20")))
    bm25_k: int = field(default_factory=lambda: int(os.getenv("BM25_K", "20")))
    rrf_k: int = field(default_factory=lambda: int(os.getenv("RRF_K", "60")))
    rerank_pool: int = field(default_factory=lambda: int(os.getenv("RERANK_POOL", "20")))
    fragment_limit: int = field(default_factory=lambda: int(os.getenv("FRAGMENT_LIMIT", "5")))
    related_max: int = field(default_factory=lambda: int(os.getenv("RELATED_MAX", "2")))
    anchor_max: int = field(default_factory=lambda: int(os.getenv("ANCHOR_MAX", "2")))
    core_min: int = field(default_factory=lambda: int(os.getenv("CORE_MIN", "2")))
    anchors_file: str = field(default_factory=lambda: os.getenv("ANCHORS_FILE", "anchors.yaml"))
    # relevance mixing (score → 0..1)
    rel_w_dense: float = field(default_factory=lambda: float(os.getenv("REL_W_DENSE", "0.7")))
    rel_w_bm25: float = field(default_factory=lambda: float(os.getenv("REL_W_BM25", "0.3")))
    rel_threshold: float = field(default_factory=lambda: float(os.getenv("REL_THRESHOLD", "0.0")))
    bm25_k1: float = field(default_factory=lambda: float(os.getenv("BM25_K1", "1.5")))
    bm25_b: float = field(default_factory=lambda: float(os.getenv("BM25_B", "0.75")))
    abbr_min_df: int = field(default_factory=lambda: int(os.getenv("ABBR_MIN_DF", "2")))
    query_max_len: int = field(default_factory=lambda: int(os.getenv("QUERY_MAX_LEN", "1000")))
    # PocketBase / auth
    pb_url: str = field(default_factory=lambda: os.getenv("PB_URL", "http://localhost:8090"))
    pb_email: str = field(default_factory=lambda: os.getenv("PB_SERVICE_EMAIL", ""))
    pb_password: str = field(default_factory=lambda: os.getenv("PB_SERVICE_PASSWORD", ""))
    auth_mode: str = field(default_factory=lambda: os.getenv("AUTH_MODE", "pocketbase"))  # pocketbase | dev
    auth_cache_ttl: float = field(default_factory=lambda: float(os.getenv("AUTH_CACHE_TTL", "30")))
    dev_access_level: int = field(default_factory=lambda: int(os.getenv("DEV_ACCESS_LEVEL", "3")))
    ingest_key: str = field(default_factory=lambda: os.getenv("INGEST_KEY", ""))
    # embeddings
    emb_model: str = field(default_factory=lambda: os.getenv("EMB_MODEL", "BAAI/bge-m3"))
