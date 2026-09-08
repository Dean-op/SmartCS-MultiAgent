from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ecommerce_ai_agent.business_tools import BusinessTools
from ecommerce_ai_agent.knowledge import KnowledgeBase
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelProviderError
from ecommerce_ai_agent.schemas.chat import AssistantMessage, ChatRequest, ChatResponse
from ecommerce_ai_agent.workflow import build_chat_workflow


class ChatService:
    def __init__(
        self,
        model: BailianModel,
        tools: BusinessTools,
        knowledge: KnowledgeBase,
        *,
        checkpointer: Any | None = None,
    ) -> None:
        self._model = model
        self._knowledge = knowledge
        self._workflow = build_chat_workflow(
            model,
            tools,
            knowledge,
            checkpointer=checkpointer,
        )

    async def respond(self, request: ChatRequest) -> ChatResponse:
        conversation_id = request.conversation_id or uuid4()
        state = await self._workflow.ainvoke(
            {
                "messages": [{"role": "user", "content": request.message}],
                "tool_used": False,
            },
            {"configurable": {"thread_id": str(conversation_id)}},
        )
        content = state["messages"][-1].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError
        return ChatResponse(
            conversation_id=conversation_id,
            message=AssistantMessage(
                id=uuid4(),
                content=content.strip(),
                created_at=datetime.now(UTC),
            ),
        )

    async def close(self) -> None:
        await self._knowledge.close()
        await self._model.close()
