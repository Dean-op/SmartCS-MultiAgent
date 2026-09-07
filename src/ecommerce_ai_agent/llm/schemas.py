from pydantic import BaseModel, ConfigDict


class MessageAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    requires_business_action: bool
    reason: str
