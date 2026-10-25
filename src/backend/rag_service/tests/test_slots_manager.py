from __future__ import annotations

import pytest

from app.core.slots_manager import update_slot_state


@pytest.mark.parametrize("message", ["Какой адресат?", "Как хранить документ?"])
def test_address_and_storage_topics_require_document_type(message: str):
    session: dict = {"slots": {}, "last_topic": None}

    result = update_slot_state(session, message)

    assert result["missing_slot"] == "вид_документа"


def test_missing_required_slot_returns_one_clarifying_question_and_remembers_topic():
    session: dict = {"slots": {}, "last_topic": None}

    result = update_slot_state(session, "Кто визирует документы?")

    assert result["missing_slot"] == "вид_документа"
    assert result["question"] == "Уточните, пожалуйста, о каком виде документа идет речь?"
    assert session["last_topic"] == "визирование"
    assert session["slots"] == {}


def test_slot_answer_from_followup_enriches_search_query():
    session: dict = {"slots": {}, "last_topic": "визирование"}

    result = update_slot_state(session, "а для распоряжения?")

    assert result["topic"] == "визирование"
    assert result["missing_slot"] is None
    assert result["query"] == "визирование распоряжение"
    assert session["slots"]["вид_документа"] == "распоряжение"


def test_topic_and_slot_in_same_message_skip_clarification():
    session: dict = {"slots": {}, "last_topic": None}

    result = update_slot_state(session, "Какой срок рассмотрения приказа?")

    assert result["topic"] == "срок"
    assert result["missing_slot"] is None
    assert result["query"] == "Какой срок рассмотрения приказа?"
    assert session["slots"]["вид_документа"] == "приказ"


def test_slot_filled_earlier_in_session_is_reused_for_new_topic():
    session: dict = {
        "slots": {"вид_документа": "приказ"},
        "last_topic": "срок",
    }

    result = update_slot_state(session, "Как хранить?")

    assert result["topic"] == "хранение"
    assert result["missing_slot"] is None
    assert result["query"] == "Как хранить? приказ"


def test_explanatory_note_requires_page_count():
    session: dict = {"slots": {}, "last_topic": None}

    missing = update_slot_state(session, "Как оформить пояснительную записку?")
    filled = update_slot_state(session, "Пояснительная записка на 3 страницах")

    assert missing["missing_slot"] == "объем_страниц"
    assert filled["missing_slot"] is None
    assert session["slots"]["объем_страниц"] == "3 страниц"
