import uuid

from pydantic import BaseModel, Field

from app.db.models import ConfidenceLevel


class QueryRequest(BaseModel):
    org_id: uuid.UUID
    question: str = Field(..., min_length=1, max_length=2000)


class Citation(BaseModel):
    document_id: uuid.UUID
    filename: str
    page: int | None = None
    section_heading: str | None = None


class LLMCitation(BaseModel):
    """Citation shape requested from the LLM's structured output. The model
    only knows chunks by an opaque `chunk_id` we hand it in the prompt; the
    app resolves that back to a real Citation after the call returns."""

    chunk_id: str


class LLMAnswer(BaseModel):
    """Expected JSON shape from the chat completion - forces citations plus
    a self-reported confidence/review flag on every answer."""

    answer: str
    confidence: ConfidenceLevel
    citations: list[LLMCitation]
    needs_human_review: bool
    reasoning_note: str | None = None


class QueryResponse(BaseModel):
    interaction_id: uuid.UUID
    answer: str
    citations: list[Citation]
    confidence: ConfidenceLevel
    needs_human_review: bool
    latency_ms: int
