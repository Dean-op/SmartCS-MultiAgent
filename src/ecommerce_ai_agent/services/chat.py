from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ecommerce_ai_agent.business_tools import TOOL_DEFINITIONS, BusinessTools
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelProviderError
from ecommerce_ai_agent.schemas.chat import AssistantMessage, ChatRequest, ChatResponse

CUSTOMER_SERVICE_SYSTEM_PROMPT = """你是一名简洁、诚实的电商智能客服。
你可以回答一般性问题，也可以使用提供的只读工具查询当前用户的订单、商品和退款。
涉及订单、商品价格或退款状态时应先调用相应工具，只能使用工具返回的数据回答。
工具返回 found=false 时，说明未找到记录或该记录不属于当前用户，不要猜测。
当前不能修改订单或数据库，也不能创建退款；用户要求写操作时应明确无法执行。
不要编造订单状态、物流、价格、退款状态或操作结果。"""


class ChatService:
    def __init__(self, model: BailianModel, tools: BusinessTools) -> None:
        self._model = model
        self._tools = tools

    async def respond(self, request: ChatRequest) -> ChatResponse:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": CUSTOMER_SERVICE_SYSTEM_PROMPT},
            {"role": "user", "content": request.message},
        ]
        content = None
        for _ in range(2):
            turn = await self._model.generate_turn(messages, TOOL_DEFINITIONS)
            if not turn.tool_calls:
                content = turn.content
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": call.arguments,
                            },
                        }
                        for call in turn.tool_calls
                    ],
                }
            )
            for call in turn.tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": await self._tools.run(call.name, call.arguments),
                    }
                )

        if content is None:
            raise ModelProviderError
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
