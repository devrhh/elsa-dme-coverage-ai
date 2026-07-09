"""POST /query - the core Q&A endpoint.

Flow: embed question -> retrieve from the org's Chroma collection only ->
gate on retrieval confidence -> (maybe) call the LLM with a guarded prompt ->
persist the interaction -> return an answer a rep can judge and verify.
"""

import time
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import NoReadyDocumentsError, OrganizationNotFoundError
from app.db.models import Document, DocumentStatus, Interaction, InteractionDocument, Organization
from app.db.session import get_db
from app.schemas.query import QueryRequest, QueryResponse
from app.services import answer_generation, retrieval

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(payload: QueryRequest, db: Session = Depends(get_db)) -> QueryResponse:
    org = db.get(Organization, payload.org_id)
    if org is None:
        raise OrganizationNotFoundError(f"Organization {payload.org_id} not found.")

    has_ready_document = (
        db.query(Document)
        .filter(Document.org_id == payload.org_id, Document.status == DocumentStatus.ready)
        .first()
    )
    if has_ready_document is None:
        raise NoReadyDocumentsError("This organization has no successfully processed documents to query yet.")

    start = time.perf_counter()

    chunks = retrieval.retrieve_chunks(payload.org_id, payload.question)
    if retrieval.is_retrieval_weak(chunks):
        llm_answer, citations = answer_generation.insufficient_context_answer()
    else:
        llm_answer, citations = answer_generation.generate_answer(payload.question, chunks)

    latency_ms = int((time.perf_counter() - start) * 1000)

    interaction = Interaction(
        org_id=payload.org_id,
        question=payload.question,
        answer=llm_answer.answer,
        confidence=llm_answer.confidence,
        needs_human_review=llm_answer.needs_human_review,
        latency_ms=latency_ms,
    )
    db.add(interaction)
    db.flush()

    seen_document_ids: set[uuid.UUID] = set()
    for citation in citations:
        if citation.document_id in seen_document_ids:
            continue
        seen_document_ids.add(citation.document_id)
        db.add(InteractionDocument(interaction_id=interaction.id, document_id=citation.document_id))

    db.commit()

    return QueryResponse(
        interaction_id=interaction.id,
        answer=llm_answer.answer,
        citations=citations,
        confidence=llm_answer.confidence,
        needs_human_review=llm_answer.needs_human_review,
        latency_ms=latency_ms,
    )
