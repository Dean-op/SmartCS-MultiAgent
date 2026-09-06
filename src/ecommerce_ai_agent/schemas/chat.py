from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MessageText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000, strict=True),
]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: MessageText = Field(description="The user's message")
    conversation_id: UUID | None = Field(
        default=None,
        description="Optional correlation identifier; it is not an authenticated identity",
    )


class AssistantMessage(BaseModel):
    id: UUID
    role: Literal["assistant"] = "assistant"
    content: str
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: UUID
    message: AssistantMessage
    status: Literal["completed"] = "completed"
    mode: Literal["mock"] = "mock"
