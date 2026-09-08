from typing import Any
from uuid import uuid4

import pytest

from ecommerce_ai_agent.llm.client import ModelTurn, StreamedText, ToolCall
from ecommerce_ai_agent.llm.errors import ModelProviderError
from ecommerce_ai_agent.llm.schemas import RouteName
from ecommerce_ai_agent.schemas.chat import ChatRequest
from ecommerce_ai_agent.services.chat import ChatService

TEST_USER_ID = uuid4()


class RecordingModel:
    def __init__(
        self,
        *turns: ModelTurn,
        route: RouteName = "order",
        general_text: str = "你好！",
    ) -> None:
        self.turns = list(turns)
        self.route = route
        self.general_text = general_text
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
        self.closed = False

    async def generate_structured(self, system_prompt, user_prompt, schema_type):
        return schema_type(route=self.route)

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        return self.general_text

    async def generate_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        self.calls.append((messages.copy(), tools))
        return self.turns.pop(0)

    async def stream_text(self, system_prompt, user_prompt, emit) -> StreamedText:
        emit("reasoning_delta", "先理解用户问题")
        emit("delta", self.general_text)
        return StreamedText(self.general_text, "先理解用户问题")

    async def stream_messages(self, messages, emit) -> StreamedText:
        return await self.stream_text("", "", emit)

    async def close(self) -> None:
        self.closed = True


class RecordingTools:
    def __init__(self, result: str = '{"found":true,"status":"shipped"}') -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def run(self, name: str, arguments: str, user_id) -> str:
        self.calls.append((name, arguments))
        return self.result


class FakeKnowledge:
    def __init__(self) -> None:
        self.closed = False

    async def search(self, question: str) -> list:
        return []

    async def close(self) -> None:
        self.closed = True


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
    service = ChatService(model, tools, FakeKnowledge())

    response = await service.respond(
        ChatRequest(message="查询订单 EC2026080016", conversation_id=conversation_id),
        TEST_USER_ID,
    )

    assert tools.calls == [("get_current_user_order", '{"order_number":"EC2026080016"}')]
    first_messages, definitions = model.calls[0]
    assert first_messages[0]["role"] == "system"
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
    model = RecordingModel(route="general", general_text="你好！")
    tools = RecordingTools()
    service = ChatService(model, tools, FakeKnowledge())

    response = await service.respond(ChatRequest(message="你好"), TEST_USER_ID)

    assert response.message.content == "你好！"
    assert tools.calls == []
    assert model.calls == []


@pytest.mark.asyncio
async def test_chat_service_streams_custom_events_and_final_payload() -> None:
    conversation_id = uuid4()
    service = ChatService(
        RecordingModel(route="general", general_text="你好！"),
        RecordingTools(),
        FakeKnowledge(),
    )

    events = [
        event
        async for event in service.stream_events(
            ChatRequest(message="你好", conversation_id=conversation_id), TEST_USER_ID
        )
    ]

    assert events[0] == {
        "event": "conversation",
        "conversation_id": str(conversation_id),
    }
    assert {event["event"] for event in events} >= {
        "conversation",
        "status",
        "reasoning_delta",
        "delta",
        "done",
    }
    assert events[-1]["content"] == "你好！"
    assert events[-1]["reasoning_content"] == "先理解用户问题"
    assert events[-1]["status"] == "completed"


@pytest.mark.asyncio
async def test_chat_service_stops_repeated_tool_calls_after_two_rounds() -> None:
    repeated = ModelTurn(
        content=None,
        tool_calls=(ToolCall(id="call", name="get_product_by_sku", arguments='{"sku":"x"}'),),
    )
    service = ChatService(
        RecordingModel(repeated, repeated, route="product"),
        RecordingTools(),
        FakeKnowledge(),
    )

    with pytest.raises(ModelProviderError):
        await service.respond(ChatRequest(message="查询商品"), TEST_USER_ID)


@pytest.mark.asyncio
async def test_chat_service_closes_model_client() -> None:
    model = RecordingModel(route="general")
    knowledge = FakeKnowledge()
    service = ChatService(model, RecordingTools(), knowledge)

    await service.close()

    assert model.closed is True
    assert knowledge.closed is True
