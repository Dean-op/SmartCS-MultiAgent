from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ecommerce_ai_agent.llm.client import ModelTurn, ToolCall
from ecommerce_ai_agent.schemas.chat import ChatRequest
from ecommerce_ai_agent.services.chat import ChatService


class ScriptedConversationModel:
    def __init__(
        self,
        *,
        routes: list[str],
        turns: list[ModelTurn] | None = None,
        texts: list[str] | None = None,
    ) -> None:
        self.routes = routes
        self.turns = turns or []
        self.texts = texts or []
        self.router_inputs: list[str] = []
        self.turn_inputs: list[list[dict[str, Any]]] = []

    async def generate_structured(self, system_prompt, user_prompt, schema_type):
        self.router_inputs.append(user_prompt)
        return schema_type(route=self.routes.pop(0))

    async def generate_turn(self, messages, tools) -> ModelTurn:
        self.turn_inputs.append(messages)
        return self.turns.pop(0)

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        return self.texts.pop(0)

    async def close(self) -> None:
        return None


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def run(self, name: str, arguments: str) -> str:
        self.calls.append((name, arguments))
        return '{"found":true,"refunds":[{"refund_number":"RF2026080001"}]}'


class EmptyKnowledge:
    async def search(self, question: str) -> list:
        return []

    async def close(self) -> None:
        return None


def order_call(call_id: str) -> ModelTurn:
    return ModelTurn(
        content=None,
        tool_calls=(
            ToolCall(
                id=call_id,
                name="get_current_user_order",
                arguments='{"order_number":"EC2026080016"}',
            ),
        ),
    )


@pytest.mark.asyncio
async def test_same_conversation_restores_order_context_and_uses_uuid_as_thread_id() -> None:
    conversation_id = uuid4()
    model = ScriptedConversationModel(
        routes=["order", "order"],
        turns=[
            order_call("first-order"),
            ModelTurn(content="首次订单回答", tool_calls=()),
            order_call("follow-up-order"),
            ModelTurn(content="订单当前仍已完成", tool_calls=()),
        ],
    )
    tools = RecordingTools()
    checkpointer = InMemorySaver()
    service = ChatService(model, tools, EmptyKnowledge(), checkpointer=checkpointer)

    await service.respond(
        ChatRequest(message="查询订单 EC2026080016", conversation_id=conversation_id)
    )
    response = await service.respond(
        ChatRequest(message="它现在是什么状态？", conversation_id=conversation_id)
    )

    assert response.conversation_id == conversation_id
    assert response.message.content == "订单当前仍已完成"
    assert len(tools.calls) == 2
    follow_up_messages = model.turn_inputs[2]
    assert any(message.get("content") == "查询订单 EC2026080016" for message in follow_up_messages)
    assert follow_up_messages[-1] == {"role": "user", "content": "它现在是什么状态？"}
    checkpoint = await checkpointer.aget_tuple(
        {"configurable": {"thread_id": str(conversation_id)}}
    )
    assert checkpoint is not None


@pytest.mark.asyncio
async def test_same_conversation_can_route_from_order_history_to_refund_agent() -> None:
    conversation_id = uuid4()
    refund_call = ModelTurn(
        content=None,
        tool_calls=(
            ToolCall(
                id="refund-call",
                name="get_current_user_refund",
                arguments='{"refund_number":"RF2026080001"}',
            ),
        ),
    )
    model = ScriptedConversationModel(
        routes=["order", "refund"],
        turns=[
            order_call("order-call"),
            ModelTurn(content="订单关联退款 RF2026080001", tool_calls=()),
            refund_call,
            ModelTurn(content="退款正在处理", tool_calls=()),
        ],
    )
    tools = RecordingTools()
    service = ChatService(
        model,
        tools,
        EmptyKnowledge(),
        checkpointer=InMemorySaver(),
    )

    await service.respond(
        ChatRequest(message="查询订单 EC2026080016", conversation_id=conversation_id)
    )
    await service.respond(
        ChatRequest(message="它有没有退款记录？", conversation_id=conversation_id)
    )

    assert [name for name, _ in tools.calls] == [
        "get_current_user_order",
        "get_current_user_refund",
    ]
    assert any("RF2026080001" in str(message.get("content")) for message in model.turn_inputs[2])


@pytest.mark.asyncio
async def test_different_conversations_do_not_share_router_context() -> None:
    first_id = uuid4()
    second_id = uuid4()
    model = ScriptedConversationModel(
        routes=["general", "general", "general"],
        texts=["已记录", "继续回答", "请提供订单号"],
    )
    service = ChatService(
        model,
        RecordingTools(),
        EmptyKnowledge(),
        checkpointer=InMemorySaver(),
    )

    await service.respond(ChatRequest(message="记住订单 EC-PRIVATE", conversation_id=first_id))
    await service.respond(ChatRequest(message="继续", conversation_id=first_id))
    await service.respond(ChatRequest(message="继续", conversation_id=second_id))

    assert "EC-PRIVATE" in model.router_inputs[1]
    assert "EC-PRIVATE" not in model.router_inputs[2]
