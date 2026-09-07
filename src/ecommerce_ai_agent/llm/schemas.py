from typing import Literal

from pydantic import BaseModel, ConfigDict

RouteName = Literal["order", "refund", "product", "general"]


class MessageAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    requires_business_action: bool
    reason: str


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: RouteName
