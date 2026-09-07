from datetime import UTC, datetime
from uuid import uuid4

from ecommerce_ai_agent.business_tools import BusinessTools
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelProviderError
from ecommerce_ai_agent.schemas.chat import AssistantMessage, ChatRequest, ChatResponse
from ecommerce_ai_agent.workflow import CUSTOMER_SERVICE_SYSTEM_PROMPT, build_chat_workflow


class ChatService:
    def __init__(self, model: BailianModel, tools: BusinessTools) -> None:
        self._model = model
        self._workflow = build_chat_workflow(model, tools)

    async def respond(self, request: ChatRequest) -> ChatResponse:
        state = await self._workflow.ainvoke(
            {
                "messages": [
                    {"role": "system", "content": CUSTOMER_SERVICE_SYSTEM_PROMPT},
                    {"role": "user", "content": request.message},
                ]
            }
        )
        content = state["messages"][-1].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError
        return ChatResponse(
            conversation_id=request.conversation_id or uuid4(),
            message=AssistantMessage(
                id=uuid4(),
                content=content.strip(),
                created_at=datetime.now(UTC),
            ),
        )

    async def close(self) -> None:
        await self._model.close()
