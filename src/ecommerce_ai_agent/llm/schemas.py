from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SpecialistRoute = Literal["order", "refund", "product", "knowledge"]
RouteName = Literal["order", "refund", "product", "knowledge", "general", "complex"]


class MessageAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    requires_business_action: bool
    reason: str


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: RouteName


class SupervisorPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: tuple[SpecialistRoute, ...] = Field(min_length=2, max_length=3)

    @field_validator("steps")
    @classmethod
    def steps_must_be_unique(
        cls, steps: tuple[SpecialistRoute, ...]
    ) -> tuple[SpecialistRoute, ...]:
        if len(set(steps)) != len(steps):
            raise ValueError("plan steps must be unique")
        return steps
