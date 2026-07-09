import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import DocumentStatus


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    filename: str
    page_count: int | None
    chunk_count: int | None
    status: DocumentStatus
    failure_reason: str | None
    uploaded_at: datetime


class DocumentListResponse(BaseModel):
    documents: list[DocumentOut]


class DocumentDeleteResponse(BaseModel):
    id: uuid.UUID
    deleted: bool
