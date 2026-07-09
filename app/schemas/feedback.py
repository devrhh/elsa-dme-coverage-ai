import uuid

from pydantic import BaseModel

from app.db.models import FeedbackVote


class FeedbackRequest(BaseModel):
    vote: FeedbackVote


class FeedbackResponse(BaseModel):
    interaction_id: uuid.UUID
    feedback: FeedbackVote
