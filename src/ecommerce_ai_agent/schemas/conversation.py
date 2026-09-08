from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from ecommerce_ai_agent.models.enums import ConversationMessageRole, ConversationMessageStatus


class ConversationSummaryResponse(BaseModel):
    conversation_id: UUID
    title: str
    last_message_preview: str
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationSummaryResponse]


class ConversationMessageResponse(BaseModel):
    id: UUID
    role: ConversationMessageRole
    content: str
    reasoning_content: str | None
    status: ConversationMessageStatus
    request_id: str | None
    trace_id: str | None
    latency_ms: float | None
    created_at: datetime


class ConversationHistoryResponse(BaseModel):
    items: list[ConversationMessageResponse]
