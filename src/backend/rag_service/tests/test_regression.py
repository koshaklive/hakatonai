from __future__ import annotations

import pytest

from app.core.chunks import load_chunks
from app.core.config import Settings
from app.search.anchors import load_anchors
from app.search.hybrid import Searcher
from app.search.index import build_lexical


@pytest.fixture(scope="module")
def searcher() -> Searcher:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    cfg = Settings(
        data_file=str(root / "data" / "instruction_chunks.json"),
        dense_enabled=False,
        use_qdrant=False,
        bm25_k=20,
        anchors_file=str(root / "anchors.yaml"),
    )
    chunks = load_chunks(cfg.data_file)
    return Searcher(cfg, build_lexical(chunks, cfg), anchors=load_anchors(cfg.anchors_file))


def assert_clause(searcher: Searcher, question: str, point: str, *phrases: str) -> None:
    result = searcher.search(question, max_access=3)
    hit = next((candidate for candidate in result.hits if candidate.point == point), None)
    assert hit is not None, f"Expected p. {point} in results for {question!r}"
    text = hit.text.casefold()
    for phrase in phrases:
        assert phrase.casefold() in text, f"Expected {phrase!r} in p. {point}"


def test_point_6_6_sets_15_calendar_days(searcher: Searcher) -> None:
    assert_clause(searcher, "п. 6.6 срок администрации высшего должностного лица", "6.6",
                  "15 календарных дней")


def test_point_6_6_sets_30_days_for_other_named_documents(searcher: Searcher) -> None:
    assert_clause(searcher, "п. 6.6 распорядительный акт календарные дни", "6.6",
                  "30 календарных дней")


def test_point_6_7_sets_three_working_days_for_urgent(searcher: Searcher) -> None:
    assert_clause(searcher, "п. 6.7 срочно срок исполнения", "6.7", "3 (трех) рабочих дней")


def test_point_6_7_sets_next_day_for_very_urgent(searcher: Searcher) -> None:
    assert_clause(searcher, "п. 6.7 весьма срочно срок исполнения", "6.7",
                  "рабочего дня, следующего за датой регистрации")


def test_point_10_3_sets_order_review_period(searcher: Searcher) -> None:
    assert_clause(searcher, "п. 10.3 приказ по основной деятельности срок", "10.3",
                  "10 рабочих дней")


def test_point_10_3_sets_directive_review_period(searcher: Searcher) -> None:
    assert_clause(searcher, "п. 10.3 распоряжение срок", "10.3", "3 рабочих дня")


def test_point_10_6_covers_document_visa_sequence(searcher: Searcher) -> None:
    assert_clause(searcher, "п. 10.6 последовательность визирования проекта документа", "10.6",
                  "визирование")


def test_point_10_11_covers_visa_matrix(searcher: Searcher) -> None:
    assert_clause(searcher, "п. 10.11 матрица обязательного визирования", "10.11",
                  "матриц")


def test_point_9_3_does_not_establish_sanctions(searcher: Searcher) -> None:
    assert_clause(searcher, "п. 9.3 официальное разъяснение санкции", "9.3",
                  "санкц")


def test_point_5_6_registers_incoming_documents_on_receipt(searcher: Searcher) -> None:
    assert_clause(searcher, "п. 5.6 регистрация входящего документа", "5.6",
                  "в день его поступления")
