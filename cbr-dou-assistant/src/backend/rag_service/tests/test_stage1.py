"""Stage-1 tests: ingest, direct match, access filter, part merging, anchors, idempotency."""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from app.core.chunks import validate
from app.core.config import Settings
from app.core.registry import Registry
from app.ingest import build_index, load_active
from app.search.direct import extract_points
from tests.conftest import ToyEmbedder, make_searcher, subset


def tmp() -> Path:
    return Path(tempfile.mkdtemp())


def test_validate_skips_virtual_and_keeps_parts():
    v = validate(subset())
    ids = {c["id"] for c in v["indexable"]}
    assert "1.4" not in ids and {"1.4#1", "1.4#2"} <= ids
    assert v["report"]["virtual_skipped"] == 1


def test_ingest_idempotent_and_registry():
    t = tmp()
    cfg = Settings(index_dir=t / "idx", qdrant_path=str(t / "q"), use_qdrant=False)
    r1 = build_index(cfg, subset(), ToyEmbedder())
    r2 = build_index(cfg, subset(), ToyEmbedder())          # second run must not duplicate anything
    assert r1["indexed"] == r2["indexed"] and r2["dense"]
    reg = Registry(cfg.index_dir).read()
    assert reg["active"] == "ОД_184" and len(reg["versions"]) == 1
    idx = load_active(cfg)
    assert len(idx.chunks) == r1["indexed"] and idx.dense is not None


def test_extract_points():
    assert extract_points("что в п. 10.6") == ["10.6"]
    assert extract_points("пункт 6.4") == ["6.4"]
    assert extract_points("в пп. 10.6 и 10.11?") == ["10.6", "10.11"]
    assert extract_points("срок до 14.10.2026") == []        # a date is not a point reference


def test_direct_match_top1():
    s = make_searcher(subset(), tmp())
    r = s.search("пункт 6.4", max_access=3)
    assert r.method == "direct" and r.hits[0].point == "6.4" and r.hits[0].relevance == 1.0


def test_unknown_point_falls_through_to_search():
    s = make_searcher(subset(), tmp())
    assert s.search("что в п. 99.9", max_access=3).method != "direct"


def test_parts_are_glued_into_one_point():
    s = make_searcher(subset(), tmp())
    r = s.search("термины и сокращения ДОУ ИИС ДО", max_access=3)
    pts = [h.point for h in r.hits]
    assert pts.count("1.4") <= 1 and not any("#" in p for p in pts)
    h = s.index.points["1.4"]
    assert len(h) == 2 and "Реестр бумажного документооборота" in s.index.point_text("1.4")


def test_access_filter_hides_chunk_everywhere():
    chunks = copy.deepcopy(subset())
    for c in chunks:
        if c["id"] == "6.4":
            c["access_level"] = 3
    s = make_searcher(chunks, tmp(), dense=True)
    assert s.search("пункт 6.4", max_access=1).method != "direct"
    assert "6.4" not in [h.point for h in s.search("до 14 октября включается ли дата", max_access=1).hits]
    assert s.search("пункт 6.4", max_access=3).hits[0].point == "6.4"


def test_anchor_forced_into_context():
    s = make_searcher(subset(), tmp())
    r = s.search("Какой срок рассмотрения приказа?", max_access=3)
    assert "10.3" in [h.point for h in r.hits] and len(r.hits) <= 5


def test_hybrid_with_dense_returns_scores_and_respects_limit():
    s = make_searcher(subset(), tmp(), dense=True)
    r = s.search("порядок визирования проекта документа", max_access=3)
    assert r.method == "hybrid" and len(r.hits) <= 5 and r.hits[0].scores["dense"] > 0


def test_parent_head_attached_to_subpoint():
    s = make_searcher(subset(), tmp())
    h = s._hit("1.5.1", 0.5, "hybrid")
    assert h.head and "1.5" not in h.point[:0]
