import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import InteractionNotFoundError
from app.db.models import Interaction
from app.db.session import get_db
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter(tags=["feedback"])


@router.post("/interactions/{interaction_id}/feedback", response_model=FeedbackResponse)
def submit_feedback(
    interaction_id: uuid.UUID,
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
) -> FeedbackResponse:
    interaction = db.get(Interaction, interaction_id)
    if interaction is None:
        raise InteractionNotFoundError(f"Interaction {interaction_id} not found.")

    interaction.feedback = payload.vote
    db.commit()

    return FeedbackResponse(interaction_id=interaction_id, feedback=payload.vote)
