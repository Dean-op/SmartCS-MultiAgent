from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from langgraph.types import Command

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

    async def respond(self, request: ChatRequest, user_id: UUID) -> ChatResponse:
        conversation_id = request.conversation_id or uuid4()
        thread_id = f"{user_id}:{conversation_id}"
        state = await self._workflow.ainvoke(
            {
                "messages": [{"role": "user", "content": request.message}],
                "tool_used": False,
                "user_id": str(user_id),
            },
            {"configurable": {"thread_id": thread_id}},
        )
        interrupts = state.get("__interrupt__", ())
        if interrupts:
            pending = interrupts[0].value
            return self._response(
                conversation_id,
                (
                    f"退款申请 {pending['refund_number']} 已提交，正在等待人工审核"
                    f"（审核编号：{pending['review_id']}）。"
                ),
                status="pending_review",
            )
        content = state["messages"][-1].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError
        return self._response(conversation_id, content.strip())

    async def resume_review(
        self,
        thread_id: str,
        conversation_id: UUID,
        decision: str,
        reviewer_id: UUID,
        note: str | None,
    ) -> ChatResponse:
        state = await self._workflow.ainvoke(
            Command(
                resume={
                    "decision": decision,
                    "reviewer_id": str(reviewer_id),
                    "note": note,
                }
            ),
            {"configurable": {"thread_id": thread_id}},
        )
        content = state["messages"][-1].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError
        return self._response(conversation_id, content.strip())

    @staticmethod
    def _response(
        conversation_id: UUID,
        content: str,
        *,
        status: str = "completed",
    ) -> ChatResponse:
        return ChatResponse(
            conversation_id=conversation_id,
            status=status,
            message=AssistantMessage(id=uuid4(), content=content, created_at=datetime.now(UTC)),
        )

    async def close(self) -> None:
        await self._knowledge.close()
        await self._model.close()
