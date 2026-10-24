"""Minimal FastAPI application for the regulations assistant."""

from fastapi import FastAPI

from src.api.schemas import ChatRequest, ChatResponse

app = FastAPI(
    title="Интеллектуальный помощник по внутренним регламентам",
    version="0.1.0",
    description="Минимальный API-каркас. Ответы по регламентам появятся после индексации базы знаний.",
)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Return a grounded refusal until source documents are indexed."""
    return ChatResponse(
        answer=(
            "В подключенной базе знаний пока нет загруженных регламентов, "
            "поэтому я не могу достоверно ответить на вопрос. "
            "Обратитесь в Департамент ДОУ или загрузите утвержденные документы."
        ),
        sources=[],
        no_answer=True,
        clarification=False,
    )
