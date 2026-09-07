from datetime import UTC, datetime
from uuid import uuid4

from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.schemas.chat import AssistantMessage, ChatRequest, ChatResponse

CUSTOMER_SERVICE_SYSTEM_PROMPT = """你是一名简洁、诚实的电商智能客服。
你可以回答一般性问题，但当前没有订单、物流、用户或退款业务工具。
不能声称已经查询真实订单或物流，不能声称已经修改订单或数据库，不能声称已经创建退款。
当用户要求执行真实业务操作时，明确说明当前无法执行，并提供一般性处理建议。
不要编造订单状态、送达时间、退款状态或操作结果。"""


class ChatService:
    def __init__(self, model: BailianModel) -> None:
        self._model = model

    async def respond(self, request: ChatRequest) -> ChatResponse:
        content = await self._model.generate_text(CUSTOMER_SERVICE_SYSTEM_PROMPT, request.message)
        return ChatResponse(
            conversation_id=request.conversation_id or uuid4(),
            message=AssistantMessage(
                id=uuid4(),
                content=content,
                created_at=datetime.now(UTC),
            ),
        )

    async def close(self) -> None:
        await self._model.close()
