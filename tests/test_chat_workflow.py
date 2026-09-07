from typing import Any

import pytest

from ecommerce_ai_agent.llm.client import ModelTurn, ToolCall
from ecommerce_ai_agent.llm.errors import ModelProviderError
from ecommerce_ai_agent.llm.schemas import RouteDecision, RouteName
from ecommerce_ai_agent.workflow import build_chat_workflow


class ScriptedModel:
    def __init__(self, route: RouteName, *turns: ModelTurn) -> None:
        self.route = route
        self.turns = list(turns)
        self.route_calls: list[tuple[str, str, type]] = []
        self.turn_tools: list[list[dict[str, Any]]] = []
        self.general_calls: list[tuple[str, str]] = []

    async def generate_structured(self, system_prompt, user_prompt, schema_type):
        self.route_calls.append((system_prompt, user_prompt, schema_type))
        return schema_type(route=self.route)

    async def generate_turn(self, messages, tools) -> ModelTurn:
        self.turn_tools.append(tools)
        return self.turns.pop(0)

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        self.general_calls.append((system_prompt, user_prompt))
        return "你好，有什么可以帮你？"


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def run(self, name: str, arguments: str) -> str:
        self.calls.append((name, arguments))
        return '{"found":true}'


async def graph_path(graph, message: str) -> list[str]:
    updates = [
        update
        async for update in graph.astream(
            {"messages": [{"role": "user", "content": message}]},
            stream_mode="updates",
        )
    ]
    return [next(iter(update)) for update in updates]


@pytest.mark.asyncio
async def test_general_route_ends_without_exposing_or_executing_business_tools() -> None:
    model = ScriptedModel("general", ModelTurn(content="wrong M5 path", tool_calls=()))
    tools = RecordingTools()
    graph = build_chat_workflow(model, tools)

    path = await graph_path(graph, "你好")

    assert path == ["router", "general_agent"]
    assert tools.calls == []
    assert model.turn_tools == []
    assert model.general_calls[0][1] == "你好"
    assert model.route_calls[0][2] is RouteDecision


@pytest.mark.parametrize(
    ("route", "agent_node", "tool_name", "arguments"),
    [
        (
            "order",
            "order_agent",
            "get_current_user_order",
            '{"order_number":"EC2026080016"}',
        ),
        (
            "refund",
            "refund_agent",
            "get_current_user_refund",
            '{"refund_number":"RF2026080001"}',
        ),
        (
            "product",
            "product_agent",
            "get_product_by_sku",
            '{"sku":"ELEC-HUB-001"}',
        ),
    ],
)
@pytest.mark.asyncio
async def test_specialist_route_exposes_only_its_tool_and_returns_through_same_agent(
    route: RouteName,
    agent_node: str,
    tool_name: str,
    arguments: str,
) -> None:
    call = ToolCall(id="call-1", name=tool_name, arguments=arguments)
    model = ScriptedModel(
        route,
        ModelTurn(content=None, tool_calls=(call,)),
        ModelTurn(content="最终回答", tool_calls=()),
    )
    tools = RecordingTools()
    graph = build_chat_workflow(model, tools)

    path = await graph_path(graph, "查询业务数据")

    assert path == ["router", agent_node, "tools", agent_node]
    assert tools.calls == [(tool_name, arguments)]
    for definitions in model.turn_tools:
        assert [tool["function"]["name"] for tool in definitions] == [tool_name]


@pytest.mark.parametrize(
    ("route", "wrong_tool", "arguments"),
    [
        ("order", "get_current_user_refund", '{"refund_number":"RF2026080001"}'),
        ("refund", "get_product_by_sku", '{"sku":"ELEC-HUB-001"}'),
        ("product", "get_current_user_order", '{"order_number":"EC2026080016"}'),
    ],
)
@pytest.mark.asyncio
async def test_specialist_rejects_another_agents_tool_call(
    route: RouteName,
    wrong_tool: str,
    arguments: str,
) -> None:
    wrong_call = ToolCall(
        id="wrong-call",
        name=wrong_tool,
        arguments=arguments,
    )
    tools = RecordingTools()
    graph = build_chat_workflow(
        ScriptedModel(route, ModelTurn(content=None, tool_calls=(wrong_call,))),
        tools,
    )

    with pytest.raises(ModelProviderError):
        await graph_path(graph, "查询订单")

    assert tools.calls == []
