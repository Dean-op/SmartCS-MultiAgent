from typing import Any
from uuid import uuid4

import pytest

from ecommerce_ai_agent.llm.client import ModelTurn, ToolCall
from ecommerce_ai_agent.llm.errors import ModelProviderError
from ecommerce_ai_agent.schemas.chat import ChatRequest
from ecommerce_ai_agent.services.chat import ChatService


class RecordingModel:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = list(turns)
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
        self.closed = False

    async def generate_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        self.calls.append((messages.copy(), tools))
        return self.turns.pop(0)

    async def close(self) -> None:
        self.closed = True


class RecordingTools:
    def __init__(self, result: str = '{"found":true,"status":"shipped"}') -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def run(self, name: str, arguments: str) -> str:
        self.calls.append((name, arguments))
        return self.result


@pytest.mark.asyncio
async def test_chat_service_executes_tool_then_returns_final_model_answer() -> None:
    conversation_id = uuid4()
    tool_call = ToolCall(
        id="call-1",
        name="get_current_user_order",
        arguments='{"order_number":"EC2026080016"}',
    )
    model = RecordingModel(
        ModelTurn(content=None, tool_calls=(tool_call,)),
        ModelTurn(content="订单正在运输中。", tool_calls=()),
    )
    tools = RecordingTools()
    service = ChatService(model, tools)

    response = await service.respond(
        ChatRequest(message="查询订单 EC2026080016", conversation_id=conversation_id)
    )

    assert tools.calls == [("get_current_user_order", '{"order_number":"EC2026080016"}')]
    first_messages, definitions = model.calls[0]
    assert first_messages[0]["role"] == "system"
    assert "只能使用工具返回的数据" in first_messages[0]["content"]
    assert first_messages[1] == {
        "role": "user",
        "content": "查询订单 EC2026080016",
    }
    assert all(
        "user_id" not in tool["function"]["parameters"]["properties"] for tool in definitions
    )
    second_messages, _ = model.calls[1]
    assert second_messages[-2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "get_current_user_order",
                    "arguments": '{"order_number":"EC2026080016"}',
                },
            }
        ],
    }
    assert second_messages[-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"found":true,"status":"shipped"}',
    }
    assert response.conversation_id == conversation_id
    assert response.message.content == "订单正在运输中。"
    assert response.mode == "llm"


@pytest.mark.asyncio
async def test_chat_service_allows_direct_answer_without_tool_execution() -> None:
    model = RecordingModel(ModelTurn(content="你好！", tool_calls=()))
    tools = RecordingTools()
    service = ChatService(model, tools)

    response = await service.respond(ChatRequest(message="你好"))

    assert response.message.content == "你好！"
    assert tools.calls == []
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_chat_service_stops_repeated_tool_calls_after_two_rounds() -> None:
    repeated = ModelTurn(
        content=None,
        tool_calls=(ToolCall(id="call", name="get_product_by_sku", arguments='{"sku":"x"}'),),
    )
    service = ChatService(RecordingModel(repeated, repeated), RecordingTools())

    with pytest.raises(ModelProviderError):
        await service.respond(ChatRequest(message="查询商品"))


@pytest.mark.asyncio
async def test_chat_service_closes_model_client() -> None:
    model = RecordingModel(ModelTurn(content="unused", tool_calls=()))
    service = ChatService(model, RecordingTools())

    await service.close()

    assert model.closed is True
