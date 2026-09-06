from datetime import UTC, datetime
from uuid import uuid4

from ecommerce_ai_agent.schemas.chat import AssistantMessage, ChatRequest, ChatResponse


class ChatService:
    async def respond(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            conversation_id=request.conversation_id or uuid4(),
            message=AssistantMessage(
                id=uuid4(),
                content="消息已接收；当前为 M1 Mock 响应，尚未接入 Agent Workflow。",
                created_at=datetime.now(UTC),
            ),
        )
