from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.models import Conversation, ConversationMessage
from ecommerce_ai_agent.models.enums import ConversationMessageStatus


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, conversation_id: UUID) -> Conversation | None:
        return await self._session.get(Conversation, conversation_id)

    async def get_message(self, message_id: UUID) -> ConversationMessage | None:
        return await self._session.get(ConversationMessage, message_id)

    async def list_for_user(self, user_id: UUID, limit: int = 50) -> list[Conversation]:
        result = await self._session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return list(result.all())

    async def list_messages(
        self, conversation_id: UUID, limit: int = 200
    ) -> list[ConversationMessage]:
        result = await self._session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(result.all()))

    async def latest_pending_review(self, conversation_id: UUID) -> ConversationMessage | None:
        return await self._session.scalar(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.status == ConversationMessageStatus.PENDING_REVIEW,
            )
            .order_by(ConversationMessage.created_at.desc())
            .limit(1)
        )

    def add(self, value: Conversation | ConversationMessage) -> None:
        self._session.add(value)

    async def flush(self) -> None:
        await self._session.flush()
