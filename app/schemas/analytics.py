import uuid
from datetime import date

from pydantic import BaseModel


class TopDocument(BaseModel):
    document_id: uuid.UUID
    filename: str
    query_count: int


class TopQuestion(BaseModel):
    question: str
    count: int


class WeeklyDocumentUsage(BaseModel):
    document_id: uuid.UUID
    filename: str
    week_start: date
    query_count: int


class AnalyticsResponse(BaseModel):
    org_id: uuid.UUID
    top_documents: list[TopDocument]
    top_questions: list[TopQuestion]
    weekly_document_usage: list[WeeklyDocumentUsage]
