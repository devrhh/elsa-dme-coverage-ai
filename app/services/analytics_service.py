"""SQL aggregation queries backing the analytics endpoint.

All queries are explicitly scoped by `org_id`, so analytics for one
organization can never surface another organization's documents or
questions.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Document, Interaction, InteractionDocument
from app.schemas.analytics import TopDocument, TopQuestion, WeeklyDocumentUsage


def top_documents(db: Session, org_id: uuid.UUID, since: datetime | None, limit: int = 10) -> list[TopDocument]:
    query = (
        db.query(
            Document.id.label("document_id"),
            Document.filename.label("filename"),
            func.count(InteractionDocument.id).label("query_count"),
        )
        .join(InteractionDocument, InteractionDocument.document_id == Document.id)
        .join(Interaction, Interaction.id == InteractionDocument.interaction_id)
        .filter(Document.org_id == org_id, Interaction.org_id == org_id)
    )
    if since is not None:
        query = query.filter(Interaction.created_at >= since)
    rows = (
        query.group_by(Document.id, Document.filename)
        .order_by(func.count(InteractionDocument.id).desc())
        .limit(limit)
        .all()
    )
    return [TopDocument(document_id=row.document_id, filename=row.filename, query_count=row.query_count) for row in rows]


def top_questions(db: Session, org_id: uuid.UUID, since: datetime | None, limit: int = 10) -> list[TopQuestion]:
    """Questions asked more than once, normalized (case/whitespace) so trivial
    rephrasing differences don't split what's really the same question. A
    question asked only once isn't "frequent" by definition, so those rows
    are filtered out via HAVING rather than in Python, to keep `limit`
    meaningful (it should cap actual frequent questions, not get padded out
    by one-off questions after the fact)."""

    normalized_question = func.lower(func.trim(Interaction.question))
    query = db.query(
        normalized_question.label("question"),
        func.count(Interaction.id).label("count"),
    ).filter(Interaction.org_id == org_id)
    if since is not None:
        query = query.filter(Interaction.created_at >= since)
    rows = (
        query.group_by(normalized_question)
        .having(func.count(Interaction.id) > 1)
        .order_by(func.count(Interaction.id).desc())
        .limit(limit)
        .all()
    )
    return [TopQuestion(question=row.question, count=row.count) for row in rows]


def weekly_document_usage(
    db: Session, org_id: uuid.UUID, since: datetime | None, limit: int = 50
) -> list[WeeklyDocumentUsage]:
    """Per-document query counts bucketed by week.

    The week bucket is computed in Python (Monday-start ISO week) rather
    than with a DB-specific function like Postgres's `date_trunc`, so this
    works the same across DB dialects without any dialect-specific SQL.
    """

    query = (
        db.query(
            Document.id.label("document_id"),
            Document.filename.label("filename"),
            Interaction.created_at.label("created_at"),
        )
        .join(InteractionDocument, InteractionDocument.document_id == Document.id)
        .join(Interaction, Interaction.id == InteractionDocument.interaction_id)
        .filter(Document.org_id == org_id, Interaction.org_id == org_id)
    )
    if since is not None:
        query = query.filter(Interaction.created_at >= since)

    counts: dict[tuple[uuid.UUID, str, datetime], int] = {}
    for row in query.all():
        week_start = (row.created_at - timedelta(days=row.created_at.weekday())).date()
        key = (row.document_id, row.filename, week_start)
        counts[key] = counts.get(key, 0) + 1

    results = [
        WeeklyDocumentUsage(document_id=doc_id, filename=filename, week_start=week_start, query_count=count)
        for (doc_id, filename, week_start), count in counts.items()
    ]
    results.sort(key=lambda r: r.week_start, reverse=True)
    return results[:limit]
