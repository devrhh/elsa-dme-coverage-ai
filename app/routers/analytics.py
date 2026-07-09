"""GET /analytics - answers the three required analytics questions, always
scoped by org_id so one organization's usage data never surfaces in
another's report."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import OrganizationNotFoundError
from app.db.models import Organization
from app.db.session import get_db
from app.schemas.analytics import AnalyticsResponse
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsResponse)
def get_analytics(
    org_id: uuid.UUID,
    since: datetime | None = None,
    limit: int = 10,
    db: Session = Depends(get_db),
) -> AnalyticsResponse:
    org = db.get(Organization, org_id)
    if org is None:
        raise OrganizationNotFoundError(f"Organization {org_id} not found.")

    return AnalyticsResponse(
        org_id=org_id,
        top_documents=analytics_service.top_documents(db, org_id, since, limit),
        top_questions=analytics_service.top_questions(db, org_id, since, limit),
        weekly_document_usage=analytics_service.weekly_document_usage(db, org_id, since, limit=limit * 5),
    )
