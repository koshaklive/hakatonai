"""Request and response schemas for the chat API."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class Source(BaseModel):
    point: str
    relevance: float = Field(ge=0.0, le=1.0)
    quote: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    no_answer: bool
    clarification: bool
