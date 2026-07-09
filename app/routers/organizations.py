"""Organization listing.

No create/update/delete API - organizations are fixed, pre-seeded reference
data (see `init_db.py`). This list endpoint just powers the frontend's
organization picker; every other endpoint still requires a real `org_id`.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.schemas.organizations import OrganizationOut

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationOut])
def list_organizations(db: Session = Depends(get_db)) -> list[Organization]:
    return db.query(Organization).order_by(Organization.name.asc()).all()
