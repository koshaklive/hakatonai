from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.chat import DETERMINISTIC_RESPONSES, ChatService, CLARIFY_ANSWER
from app.core.config import Settings
from app.core.intent import analyze_intent


@pytest.mark.parametrize("query", [
    "покороче",
    "объясни проще",
    "поясни понятнее",
    "ещё раз",
    "на примере, пожалуйста",
    "сделай ответ покороче",
])
def test_reformulation_requests_are_detected(query):
    assert analyze_intent(query) == {"action": "reformulate", "intent": "reformulate"}


def test_substantive_question_with_reformulation_word_still_uses_search():
    assert analyze_intent("Объясни порядок оформления распоряжения") == {
        "action": "search",
        "mode": "explain",
    }


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("Привет, как дела?", "smalltalk"),
        ("Мне грустно", "emotion"),
        ("У меня болит голова", "off_topic"),
        ("Сколько стоит лечение?", "off_topic"),
        ("Как оформить командировочные?", "out_of_domain"),
        ("Как оформить отпуск?", "out_of_domain"),
        ("Как выдать доверенность?", "partial_match"),
        ("Ты идиот", "rudeness"),
        ("Спасибо большое", "gratitude"),
    ],
)
def test_deterministic_intents_are_detected(query, intent):
    assert analyze_intent(query) == {"action": "reply", "intent": intent}


@pytest.mark.parametrize("query", ["Не поняла", "Не понял", "Что это значит?"])
def test_explanation_requests_are_detected(query):
    assert analyze_intent(query) == {"action": "clarify", "intent": "clarification"}


class _UnusedSearcher:
    def search(self, *args, **kwargs):
        raise AssertionError("deterministic intent must not search")


class _NoCallLLM:
    def chat(self, *args, **kwargs):
        raise AssertionError("deterministic intent must not call the LLM")


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("Привет!", "smalltalk"),
        ("Мне грустно", "emotion"),
        ("У меня болит голова", "off_topic"),
        ("Сколько стоит лечение?", "off_topic"),
        ("Нужны командировочные", "out_of_domain"),
        ("Нужен отпуск", "out_of_domain"),
        ("Нужна доверенность", "partial_match"),
        ("Ты идиот", "rudeness"),
        ("Спасибо", "gratitude"),
    ],
)
def test_deterministic_replies_skip_search_and_llm(query, intent, tmp_path):
    service = ChatService(
        Settings(calibration_file=str(tmp_path / "missing.json")),
        _UnusedSearcher(),
        _NoCallLLM(),
    )

    answer = service.answer(query)

    assert answer.llm_calls == 0
    assert answer.reason == intent
    assert answer.answer in DETERMINISTIC_RESPONSES[intent]


class _ExplainLLM:
    def __init__(self):
        self.messages = None

    def chat(self, messages, **kwargs):
        self.messages = messages
        return SimpleNamespace(text="Стало понятнее? Это значит, что сначала документ проверяют.")

    def chat_stream(self, messages):
        self.messages = messages
        yield "Это значит, что сначала документ проверяют."


def test_explanation_reuses_last_answer_and_context_without_search(tmp_path):
    llm = _ExplainLLM()
    service = ChatService(
        Settings(calibration_file=str(tmp_path / "missing.json")),
        _UnusedSearcher(),
        llm,
    )

    answer = service.answer(
        "Не понял",
        history=[{"role": "assistant", "content": "Документ проходит проверку."}],
        last_context="Перед регистрацией документ проверяется ответственным сотрудником.",
    )

    assert answer.llm_calls == 1
    assert answer.answer.endswith("Стало понятнее?")
    assert llm.messages[0]["content"] == CLARIFY_ANSWER
    assert "Документ проходит проверку." in llm.messages[1]["content"]
    assert "Перед регистрацией документ проверяется ответственным сотрудником." in llm.messages[1]["content"]


def test_stream_explanation_uses_last_answer_without_search(tmp_path):
    llm = _ExplainLLM()
    service = ChatService(
        Settings(calibration_file=str(tmp_path / "missing.json")),
        _UnusedSearcher(),
        llm,
    )

    events = list(service.stream_events(
        "Не поняла",
        history=[{"role": "assistant", "content": "Предыдущий ответ."}],
        last_context="Фрагмент инструкции для пояснения.",
    ))

    assert events[-1][0] == "done"
    assert events[-1][1]["answer"].endswith("Стало понятнее?")
    assert events[-1][1]["no_answer"] is False
    assert "Предыдущий ответ." in llm.messages[1]["content"]


def test_explanation_without_context_does_not_call_llm(tmp_path):
    service = ChatService(
        Settings(calibration_file=str(tmp_path / "missing.json")),
        _UnusedSearcher(),
        _NoCallLLM(),
    )

    answer = service.answer(
        "Что это значит?",
        history=[{"role": "assistant", "content": "Предыдущий ответ."}],
    )

    assert answer.llm_calls == 0
    assert "текстом фрагмента" in answer.answer


def test_required_warm_reply_categories_keep_their_promised_content():
    assert all(
        "Если на душе тяжело, поговорите с близкими или руководителем" in reply
        and "по работе" in reply
        for reply in DETERMINISTIC_RESPONSES["emotion"]
    )
    assert all(
        reply.startswith("В Инструкции по документообороту про это нет. Лучше уточнить в Департаменте ДОУ.")
        and "С документами помогу:" in reply
        for reply in DETERMINISTIC_RESPONSES["out_of_domain"]
    )
    assert all(
        "[п. 8.19.5]" in reply and "[п. 8.23]" in reply and "не описан" in reply
        for reply in DETERMINISTIC_RESPONSES["partial_match"]
    )
