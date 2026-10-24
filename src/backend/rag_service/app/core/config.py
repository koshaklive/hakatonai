"""Configuration: every threshold, path and flag comes from .env (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
_SERVICE_ROOT = Path(__file__).resolve().parents[2]


def _b(key: str, default: str) -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}


def _configured_file(key: str, default: str, root: Path) -> str:
    path = Path(os.getenv(key, default))
    return str(path if path.is_absolute() else root / path)


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
    rel_threshold: float = field(default_factory=lambda: float(os.getenv("REL_THRESHOLD", "0.574")))
    dense_min_relevance: float = field(default_factory=lambda: float(os.getenv("DENSE_MIN_RELEVANCE", "0.10")))
    bm25_min_relevance: float = field(default_factory=lambda: float(os.getenv("BM25_MIN_RELEVANCE", "0.08")))
    keyword_overlap_min: float = field(default_factory=lambda: float(os.getenv("KEYWORD_OVERLAP_MIN", "0.20")))
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
        # --- stage 3 ---
    pb_users_collection: str = field(default_factory=lambda: os.getenv("PB_USERS_COLLECTION", "users"))
    pb_messages: str = field(default_factory=lambda: os.getenv("PB_MESSAGES_COLLECTION", "messages"))
    pb_audit: str = field(default_factory=lambda: os.getenv("PB_AUDIT_COLLECTION", "audit_log"))
    warmup: bool = field(default_factory=lambda: _b("WARMUP", "1"))
    clarify_llm: bool = field(default_factory=lambda: _b("CLARIFY_LLM", "1"))
    gray_margin: float = field(default_factory=lambda: float(os.getenv("GRAY_MARGIN", "0.05")))
    calibration_file: str = field(default_factory=lambda: os.getenv("CALIBRATION_FILE", "data/calibration.json"))
    gold_file: str = field(default_factory=lambda: _configured_file("GOLD_FILE", "eval/gold.json", _PROJECT_ROOT))
    ood_file: str = field(default_factory=lambda: _configured_file("OOD_FILE", "tests/ood.json", _SERVICE_ROOT))
