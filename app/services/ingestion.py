"""Ingestion orchestration: extract -> chunk -> embed -> index -> record.

Runs synchronously within the upload request. Any failure at any stage is
caught and recorded on the document as `failed` rather than propagating, so
a bad upload never leaves a document stuck in `processing` or crashes the
request.
"""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import InvalidPdfError
from app.core.timeouts import TimeoutExceededError, run_with_timeout
from app.db.models import Document, DocumentStatus
from app.services import chunking, embeddings, pdf_processing, vector_store

settings = get_settings()


def ingest_document(db: Session, document: Document, file_path: str) -> None:
    try:
        blocks = run_with_timeout(
            pdf_processing.extract_structured_blocks,
            args=(file_path, settings.max_pdf_pages, settings.max_extracted_chars),
            timeout_seconds=settings.pdf_extraction_timeout_seconds,
        )

        chunks = chunking.chunk_blocks(
            blocks,
            chunk_size_tokens=settings.chunk_size_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )

        if not chunks:
            document.status = DocumentStatus.failed
            document.failure_reason = "No extractable text or tables were found in this PDF."
            db.commit()
            return

        texts = [chunk["text"] for chunk in chunks]
        vectors = embeddings.embed_texts(texts)

        vector_store.add_chunks(
            org_id=document.org_id,
            document_id=document.id,
            filename=document.filename,
            chunks=chunks,
            embeddings=vectors,
        )

        page_numbers = [block["page"] for block in blocks if block.get("page")]
        document.page_count = max(page_numbers) if page_numbers else None
        document.chunk_count = len(chunks)
        document.status = DocumentStatus.ready
        document.failure_reason = None
        db.commit()

    except InvalidPdfError as exc:
        document.status = DocumentStatus.failed
        document.failure_reason = str(exc)
        db.commit()
    except TimeoutExceededError:
        document.status = DocumentStatus.failed
        document.failure_reason = "PDF processing timed out - the file may be malformed or too complex."
        db.commit()
    except Exception as exc:  # noqa: BLE001 - ingestion must never crash the request
        document.status = DocumentStatus.failed
        document.failure_reason = f"Unexpected error during processing: {exc}"
        db.commit()
