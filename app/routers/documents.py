"""Document management: upload, list, delete - always scoped by org_id.

Isolation note: `list_documents` and `delete_document` both filter by
`org_id` at the query level (not just by document id), so a caller can never
list or delete another organization's document even if it somehow guesses a
valid document_id.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import DocumentNotFoundError, OrganizationNotFoundError
from app.db.models import Document, DocumentStatus, Organization
from app.db.session import get_db
from app.schemas.documents import DocumentDeleteResponse, DocumentListResponse, DocumentOut
from app.services import ingestion, pdf_processing, vector_store

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()


def _get_org_or_404(db: Session, org_id: uuid.UUID) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise OrganizationNotFoundError(f"Organization {org_id} not found.")
    return org


@router.post("", response_model=DocumentOut, status_code=201)
def upload_document(
    org_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Document:
    _get_org_or_404(db, org_id)

    data = file.file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    pdf_processing.validate_pdf_bytes(data, max_bytes)

    document = Document(
        org_id=org_id,
        filename=file.filename or "document.pdf",
        storage_path="",
        status=DocumentStatus.processing,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    storage_path = pdf_processing.save_pdf_file(data, org_id, document.id, settings.upload_dir)
    document.storage_path = storage_path
    db.commit()

    ingestion.ingest_document(db, document, storage_path)
    db.refresh(document)
    return document


@router.get("", response_model=DocumentListResponse)
def list_documents(org_id: uuid.UUID, db: Session = Depends(get_db)) -> DocumentListResponse:
    _get_org_or_404(db, org_id)
    documents = (
        db.query(Document).filter(Document.org_id == org_id).order_by(Document.uploaded_at.desc()).all()
    )
    return DocumentListResponse(documents=documents)


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_document(
    document_id: uuid.UUID,
    org_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DocumentDeleteResponse:
    _get_org_or_404(db, org_id)
    document = (
        db.query(Document).filter(Document.id == document_id, Document.org_id == org_id).first()
    )
    if document is None:
        raise DocumentNotFoundError(f"Document {document_id} not found for this organization.")

    vector_store.delete_document_chunks(org_id, document_id)

    file_path = Path(document.storage_path)
    if file_path.exists():
        file_path.unlink()

    db.delete(document)
    db.commit()
    return DocumentDeleteResponse(id=document_id, deleted=True)
