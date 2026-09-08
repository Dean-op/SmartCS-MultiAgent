from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.models import Conversation, ConversationMessage
from ecommerce_ai_agent.models.enums import ConversationMessageRole, ConversationMessageStatus
from ecommerce_ai_agent.repositories.conversation import ConversationRepository
from ecommerce_ai_agent.services.data_types import ConversationData, ConversationMessageData


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = ConversationRepository(session)

    async def start_turn(
        self, user_id: UUID, conversation_id: UUID, content: str
    ) -> ConversationTurn | None:
        now = datetime.now(UTC)
        conversation = await self._repository.get(conversation_id)
        if conversation is not None and conversation.user_id != user_id:
            return None
        if conversation is None:
            conversation = Conversation(
                id=conversation_id,
                user_id=user_id,
                title=content.strip()[:30],
                last_message_preview=content.strip()[:200],
                created_at=now,
                updated_at=now,
            )
            self._repository.add(conversation)
        else:
            conversation.last_message_preview = content.strip()[:200]
            conversation.updated_at = now
        user_message = ConversationMessage(
            conversation_id=conversation_id,
            role=ConversationMessageRole.USER,
            content=content,
            status=ConversationMessageStatus.COMPLETED,
            created_at=now,
        )
        assistant_message = ConversationMessage(
            conversation_id=conversation_id,
            role=ConversationMessageRole.ASSISTANT,
            content="",
            status=ConversationMessageStatus.PENDING,
            created_at=now + timedelta(microseconds=1),
        )
        self._repository.add(user_message)
        self._repository.add(assistant_message)
        await self._repository.flush()
        return ConversationTurn(conversation_id, user_message.id, assistant_message.id)

    async def complete_assistant(
        self,
        message_id: UUID,
        *,
        content: str,
        reasoning_content: str | None,
        status: ConversationMessageStatus,
        request_id: str | None = None,
        trace_id: str | None = None,
        latency_ms: float | None = None,
    ) -> bool:
        message = await self._repository.get_message(message_id)
        if message is None:
            return False
        message.content = content
        message.reasoning_content = reasoning_content
        message.status = status
        message.request_id = request_id
        message.trace_id = trace_id
        message.latency_ms = latency_ms
        conversation = await self._repository.get(message.conversation_id)
        if conversation is not None:
            conversation.last_message_preview = content.strip()[:200] or status.value
            conversation.updated_at = datetime.now(UTC)
        await self._repository.flush()
        return True

    async def list_conversations(self, user_id: UUID) -> list[ConversationData]:
        return [
            ConversationData.model_validate(item)
            for item in await self._repository.list_for_user(user_id)
        ]

    async def list_messages(
        self, user_id: UUID, conversation_id: UUID
    ) -> list[ConversationMessageData] | None:
        conversation = await self._repository.get(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            return None
        return [
            ConversationMessageData.model_validate(item)
            for item in await self._repository.list_messages(conversation_id)
        ]
