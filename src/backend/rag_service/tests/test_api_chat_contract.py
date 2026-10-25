from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.chat import DETERMINISTIC_RESPONSES
from app.api import main as api
from app.audit import Audit
from app.core.config import Settings
from app.search.index import build_lexical
from tests.conftest import subset


class FakeChatService:
    histories: list[list[dict[str, str]]] = []
    questions: list[str] = []
    stream_questions: list[str] = []

    def __init__(self, cfg, searcher, llm) -> None:
        self.low, self.high = 0.4, 0.6

    def answer(self, question, history, max_access):
        self.questions.append(question)
        return SimpleNamespace(
            answer="Обычный ответ",
            sources=[],
            refused=False,
            clarification=None,
            query=question,
            timings_ms={"total": 1},
            gray_zone=False,
            context_text="Текст фрагмента",
        )

    def stream_events(self, message, history, max_access):
        self.stream_questions.append(message)
        self.histories.append(history.copy())
        yield "sources", {"sources": [], "query_used": message}
        yield "delta", {"text": "Ответ"}
        yield "done", {
            "answer": "Ответ",
            "sources": [],
            "no_answer": False,
            "clarification": None,
            "query_used": message,
            "latency_ms": 1,
            "gray_zone": False,
        }


class FakeLLM:
    def __init__(self) -> None:
        pass

    def health(self, ping=False):
        return {"ok": True}


def test_chat_and_stream_accept_json_contract_and_share_session_history(monkeypatch, tmp_path):
    cfg = Settings(
        index_dir=tmp_path / "indexes",
        auth_mode="dev",
        dense_enabled=False,
        use_qdrant=False,
        warmup=False,
    )
    index = build_lexical(subset(), cfg)
    FakeChatService.histories.clear()
    FakeChatService.questions.clear()
    FakeChatService.stream_questions.clear()
    api.SESSIONS.pop("chat-contract-test", None)
    api.SESSIONS.pop("chat-slots-test", None)
    monkeypatch.setattr(api, "make_embedder", lambda _: None)
    monkeypatch.setattr(api, "load_active", lambda _: index)
    monkeypatch.setattr(api, "ChatService", FakeChatService)
    monkeypatch.setattr("llm_layer.llm.LLM", FakeLLM)
    monkeypatch.setattr(Audit, "chat", lambda *args, **kwargs: None)

    with TestClient(api.create_app(cfg)) as client:
        options_response = client.options(
            "/chat",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
        )
        chat_response = client.post("/chat", json={
            "message": "Какой срок рассмотрения приказа?",
            "history": [],
            "conversation_id": "chat-contract-test",
        })
        stream_response = client.post("/chat/stream", json={
            "message": "Какой срок рассмотрения приказа?",
            "history": [],
            "conversation_id": "chat-contract-test",
        })
        reply_response = client.post("/chat", json={
            "message": "Спасибо!",
            "history": [],
            "conversation_id": "chat-reply-test",
        })
        reply_stream_response = client.post("/chat/stream", json={
            "message": "Спасибо!",
            "history": [],
            "conversation_id": "chat-reply-stream-test",
        })
        slot_question_response = client.post("/chat", json={
            "message": "Кто визирует документы?",
            "history": [],
            "conversation_id": "chat-slots-test",
        })
        slot_answer_response = client.post("/chat", json={
            "message": "а для распоряжения?",
            "history": [],
            "conversation_id": "chat-slots-test",
        })
        stream_slot_response = client.post("/chat/stream", json={
            "message": "Какой срок?",
            "history": [],
            "conversation_id": "chat-stream-slots-test",
        })

    assert options_response.status_code == 200
    assert options_response.headers.get("access-control-allow-origin") in {"*", "http://localhost:3000"}
    assert chat_response.status_code == 200
    assert chat_response.json()["conversation_id"] == "chat-contract-test"
    assert chat_response.json()["answer"] == "Обычный ответ"
    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert "event: sources\n" in stream_response.text
    assert "event: delta\n" in stream_response.text
    assert '"conversation_id": "chat-contract-test"' in stream_response.text
    assert reply_response.status_code == 200
    assert reply_response.json()["answer"] in DETERMINISTIC_RESPONSES["gratitude"]
    assert reply_stream_response.status_code == 200
    assert any(
        f'"answer": "{reply}"' in reply_stream_response.text
        for reply in DETERMINISTIC_RESPONSES["gratitude"]
    )
    assert slot_question_response.json()["intent"] == "slot_clarification"
    assert slot_question_response.json()["answer"] == "Уточните, пожалуйста, о каком виде документа идет речь?"
    assert slot_answer_response.status_code == 200
    assert slot_answer_response.json()["answer"] == "Обычный ответ"
    assert api.SESSIONS["chat-slots-test"]["slots"] == {"вид_документа": "распоряжение"}
    assert api.SESSIONS["chat-slots-test"]["last_topic"] == "визирование"
    assert "визирование распоряжение" in FakeChatService.questions
    assert stream_slot_response.status_code == 200
    assert "Уточните, пожалуйста, о каком виде документа идет речь?" in stream_slot_response.text
    assert api.SESSIONS["chat-stream-slots-test"]["last_topic"] == "срок"
    assert FakeChatService.stream_questions == ["Какой срок рассмотрения приказа?"]
    assert FakeChatService.histories == [[
        {"role": "user", "content": "Какой срок рассмотрения приказа?"},
        {"role": "assistant", "content": "Обычный ответ"},
    ]]
    assert api.SESSIONS["chat-contract-test"]["history"][-2:] == [
        {"role": "user", "content": "Какой срок рассмотрения приказа?"},
        {"role": "assistant", "content": "Ответ"},
    ]
