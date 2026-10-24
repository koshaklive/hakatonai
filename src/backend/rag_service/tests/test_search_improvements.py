from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.chat import ChatService, Run
from app.core.config import Settings
from app.core.intent import analyze_intent
from app.core.search import normalize_query, passes_hybrid_filter
from app.search.hybrid import SearchResult, Searcher
from app.search.index import build_lexical
from app.core.chunks import load_chunks


@pytest.fixture(scope="module")
def corpus_searcher() -> Searcher:
    root = Path(__file__).resolve().parents[1]
    cfg = Settings(
        data_file=str(root / "data" / "corpus_chunks.json"),
        dense_enabled=False,
        use_qdrant=False,
        bm25_k=20,
        anchors_file=str(root / "anchors.yaml"),
    )
    return Searcher(cfg, build_lexical(load_chunks(cfg.data_file), cfg))


def test_normalize_query_removes_messenger_header_and_lead_ins() -> None:
    assert normalize_query("YARCHE — 22:03\nПодскажи, по правилам Инструкции: срок?") == "срок?"


@pytest.mark.parametrize(
    ("dense", "bm25", "overlap", "expected"),
    [
        (0.01, 0.25, 0.0, True),
        (0.01, 0.0, 0.4, True),
        (0.01, 0.0, 0.0, False),
    ],
)
def test_hybrid_filter_accepts_independent_evidence(
    dense: float, bm25: float, overlap: float, expected: bool
) -> None:
    assert passes_hybrid_filter(
        dense,
        bm25,
        overlap,
        dense_min=0.1,
        bm25_min=0.08,
        overlap_min=0.2,
    ) is expected


@pytest.mark.parametrize("query", ["сколько можно ждать", "тормозишь"])
def test_frustration_intent_is_detected(query: str) -> None:
    assert analyze_intent(query) == {
        "action": "search",
        "intent": "frustration",
        "mode": "frustration",
    }


def test_visa_queries_force_matrix_anchors(corpus_searcher: Searcher) -> None:
    result = corpus_searcher.search("порядок визирования проекта документа", max_access=3)

    points = {hit.point for hit in result.hits}
    assert "10.6" in points
    assert any(point.startswith("MTX.") for point in points)


def test_visa_anchor_reserves_point_10_6_when_result_is_full(corpus_searcher: Searcher) -> None:
    matrix_hits = [
        corpus_searcher._hit(point, 0.0, "anchor")
        for point in ("MTX.ext.1", "MTX.ext.2", "MTX.ext.3", "MTX.int.1", "MTX.int.2")
    ]

    result = corpus_searcher._visa_anchors("визирование", matrix_hits, max_access=3, limit=5)

    assert len(result) == 5
    assert "10.6" in {hit.point for hit in result}


class _FixedSearcher:
    def __init__(self, base: Searcher, point: str, relevance: float, scores: dict[str, float]) -> None:
        self.index = base.index
        self.hit = base._hit(point, relevance, "hybrid", scores=scores)
        self.result = SearchResult("", "lexical", [self.hit], relevance, self.index.version, {})

    def search(self, query: str, **kwargs) -> SearchResult:
        self.result.query = query
        return self.result


@pytest.fixture
def chat_base_searcher() -> Searcher:
    root = Path(__file__).resolve().parents[1]
    cfg = Settings(
        data_file=str(root / "data" / "instruction_chunks.json"),
        dense_enabled=False,
        use_qdrant=False,
        bm25_k=20,
        anchors_file=str(root / "anchors.yaml"),
    )
    return Searcher(cfg, build_lexical(load_chunks(cfg.data_file), cfg))


def _chat_service(tmp_path: Path, base: Searcher, relevance: float, scores: dict[str, float]) -> ChatService:
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps({"gray_low": 0.4, "gray_high": 0.6}), encoding="utf-8")
    cfg = Settings(calibration_file=str(calibration))
    return ChatService(cfg, _FixedSearcher(base, "6.6", relevance, scores), llm=None)


def test_gray_zone_does_not_refuse_and_adds_caveat(
    tmp_path: Path, chat_base_searcher: Searcher
) -> None:
    service = _chat_service(tmp_path, chat_base_searcher, 0.5, {})

    finished, state = service.prepare(Run(), "кварцевый фиолетовый планетарий", None, 3)

    assert finished is None
    assert state["gray"] is True
    assert "возможно, неполно" in state["messages"][0]["content"]


def test_strong_lexical_evidence_prevents_below_threshold_refusal(
    tmp_path: Path, chat_base_searcher: Searcher
) -> None:
    service = _chat_service(tmp_path, chat_base_searcher, 0.1, {"bm25n": 0.2})

    finished, state = service.prepare(Run(), "кварцевый фиолетовый планетарий", None, 3)

    assert finished is None
    assert state["gray"] is False


def test_weak_dense_and_lexical_evidence_refuses(
    tmp_path: Path, chat_base_searcher: Searcher
) -> None:
    service = _chat_service(tmp_path, chat_base_searcher, 0.1, {"dense": 0.01, "bm25n": 0.01})

    finished, state = service.prepare(Run(), "кварцевый фиолетовый планетарий", None, 3)

    assert finished is not None
    assert finished.refused is True
    assert finished.reason == "below_threshold"
