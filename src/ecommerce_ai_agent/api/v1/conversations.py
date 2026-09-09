from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from ecommerce_ai_agent.api.dependencies import get_current_user
from ecommerce_ai_agent.api.errors import ApplicationError
from ecommerce_ai_agent.schemas.conversation import (
    ConversationHistoryResponse,
    ConversationListResponse,
    ConversationMessageResponse,
    ConversationSummaryResponse,
)
from ecommerce_ai_agent.services.conversation import ConversationService
from ecommerce_ai_agent.services.data_types import UserData

router = APIRouter(prefix="/conversations")


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    request: Request,
    current_user: Annotated[UserData, Depends(get_current_user)],
) -> ConversationListResponse:
    async with request.app.state.database.session_factory() as session:
        conversations = await ConversationService(session).list_conversations(current_user.id)
    return ConversationListResponse(
        items=[
            ConversationSummaryResponse(
                conversation_id=item.id,
                title=item.title,
                last_message_preview=item.last_message_preview,
                updated_at=item.updated_at,
            )
            for item in conversations
        ]
    )


@router.get("/{conversation_id}/messages", response_model=ConversationHistoryResponse)
async def conversation_messages(
    conversation_id: UUID,
    request: Request,
    current_user: Annotated[UserData, Depends(get_current_user)],
) -> ConversationHistoryResponse:
    async with request.app.state.database.session_factory() as session:
        messages = await ConversationService(session).list_messages(
            current_user.id, conversation_id
        )
    if messages is None:
        raise ApplicationError(
            code="conversation_not_found",
            message="Conversation not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    items = [
        ConversationMessageResponse.model_validate(item, from_attributes=True) for item in messages
    ]
    safety = getattr(request.app.state, "safety_service", None)
    if safety is not None:
        for item in items:
            item.content = safety.redact_pii(item.content).text
            if item.reasoning_content:
                item.reasoning_content = safety.redact_pii(item.reasoning_content).text
    return ConversationHistoryResponse(items=items)
