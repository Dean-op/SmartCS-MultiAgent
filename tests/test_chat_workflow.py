from typing import Any

import pytest

from ecommerce_ai_agent.llm.client import ModelTurn, ToolCall
from ecommerce_ai_agent.workflow import build_chat_workflow


class ScriptedModel:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = list(turns)

    async def generate_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        return self.turns.pop(0)


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def run(self, name: str, arguments: str) -> str:
        self.calls.append((name, arguments))
        return '{"found":true,"unit_price":"299.00"}'


async def graph_path(graph, messages: list[dict[str, Any]]) -> list[str]:
    updates = [
        update async for update in graph.astream({"messages": messages}, stream_mode="updates")
    ]
    return [next(iter(update)) for update in updates]


@pytest.mark.asyncio
async def test_graph_ends_after_model_when_no_tool_is_requested() -> None:
    tools = RecordingTools()
    graph = build_chat_workflow(
        ScriptedModel(ModelTurn(content="你好！", tool_calls=())),
        tools,
    )

    path = await graph_path(graph, [{"role": "user", "content": "你好"}])

    assert path == ["model"]
    assert tools.calls == []


@pytest.mark.asyncio
async def test_graph_routes_model_to_tools_and_back_to_model() -> None:
    call = ToolCall(
        id="call-product",
        name="get_product_by_sku",
        arguments='{"sku":"ELEC-HUB-001"}',
    )
    tools = RecordingTools()
    graph = build_chat_workflow(
        ScriptedModel(
            ModelTurn(content=None, tool_calls=(call,)),
            ModelTurn(content="该商品售价 299 元。", tool_calls=()),
        ),
        tools,
    )

    path = await graph_path(
        graph,
        [{"role": "user", "content": "ELEC-HUB-001 多少钱？"}],
    )

    assert path == ["model", "tools", "model"]
    assert tools.calls == [("get_product_by_sku", '{"sku":"ELEC-HUB-001"}')]
