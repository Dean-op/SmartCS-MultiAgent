from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReviewActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    note: str | None = Field(default=None, max_length=1000)


class PendingReviewResponse(BaseModel):
    review_id: UUID
    refund_number: str
    amount: Decimal
    reason: str
    created_at: datetime
