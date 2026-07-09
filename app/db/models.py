import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import GUID


class DocumentStatus(str, enum.Enum):
    processing = "processing"
    ready = "ready"
    failed = "failed"


class FeedbackVote(str, enum.Enum):
    up = "up"
    down = "down"


class ConfidenceLevel(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    documents: Mapped[list["Document"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    interactions: Mapped[list["Interaction"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("organizations.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.processing, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="documents")
    interaction_links: Mapped[list["InteractionDocument"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("organizations.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[ConfidenceLevel | None] = mapped_column(Enum(ConfidenceLevel), nullable=True)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback: Mapped[FeedbackVote | None] = mapped_column(Enum(FeedbackVote), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    organization: Mapped["Organization"] = relationship(back_populates="interactions")
    document_links: Mapped[list["InteractionDocument"]] = relationship(back_populates="interaction", cascade="all, delete-orphan")


class InteractionDocument(Base):
    """Join table: which document(s) were used to answer a given interaction."""

    __tablename__ = "interaction_documents"
    __table_args__ = (UniqueConstraint("interaction_id", "document_id", name="uq_interaction_document"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    interaction_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("interactions.id"), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("documents.id"), nullable=False, index=True)

    interaction: Mapped["Interaction"] = relationship(back_populates="document_links")
    document: Mapped["Document"] = relationship(back_populates="interaction_links")
