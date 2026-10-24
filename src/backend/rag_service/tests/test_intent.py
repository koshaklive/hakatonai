from __future__ import annotations

import pytest

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
