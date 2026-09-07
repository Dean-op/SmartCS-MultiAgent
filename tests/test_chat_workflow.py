from typing import Any

import pytest

from ecommerce_ai_agent.knowledge import SearchResult
from ecommerce_ai_agent.llm.client import ModelTurn, ToolCall
from ecommerce_ai_agent.llm.errors import ModelProviderError
from ecommerce_ai_agent.llm.schemas import RouteDecision, RouteName, SupervisorPlan
from ecommerce_ai_agent.workflow import build_chat_workflow


class ScriptedModel:
    def __init__(
        self,
        route: RouteName,
        *turns: ModelTurn,
        plan: tuple[str, ...] = (),
        text_response: str = "你好，有什么可以帮你？",
        text_responses: tuple[str, ...] | None = None,
    ) -> None:
        self.route = route
        self.turns = list(turns)
        self.plan = plan
        self.text_responses = list(text_responses or (text_response,))
        self.route_calls: list[tuple[str, str, type]] = []
        self.turn_tools: list[list[dict[str, Any]]] = []
        self.general_calls: list[tuple[str, str]] = []

    async def generate_structured(self, system_prompt, user_prompt, schema_type):
        self.route_calls.append((system_prompt, user_prompt, schema_type))
        if schema_type is RouteDecision:
            return schema_type(route=self.route)
        return schema_type(steps=self.plan)

    async def generate_turn(self, messages, tools) -> ModelTurn:
        self.turn_tools.append(tools)
        return self.turns.pop(0)

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        self.general_calls.append((system_prompt, user_prompt))
        return self.text_responses.pop(0)


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def run(self, name: str, arguments: str) -> str:
        self.calls.append((name, arguments))
        return '{"found":true}'


class FakeKnowledge:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.questions: list[str] = []

    async def search(self, question: str) -> list[SearchResult]:
        self.questions.append(question)
        return self.results


async def graph_updates(graph, message: str) -> list[dict[str, Any]]:
    return [
        update
        async for update in graph.astream(
            {"messages": [{"role": "user", "content": message}]},
            stream_mode="updates",
        )
    ]


async def graph_path(graph, message: str) -> list[str]:
    return [next(iter(update)) for update in await graph_updates(graph, message)]


@pytest.mark.asyncio
async def test_general_route_ends_without_exposing_or_executing_business_tools() -> None:
    model = ScriptedModel("general", ModelTurn(content="wrong M5 path", tool_calls=()))
    tools = RecordingTools()
    graph = build_chat_workflow(model, tools, FakeKnowledge([]))

    path = await graph_path(graph, "你好")

    assert path == ["router", "general_agent"]
    assert tools.calls == []
    assert model.turn_tools == []
    assert model.general_calls[0][1] == "你好"
    assert model.route_calls[0][2] is RouteDecision


@pytest.mark.asyncio
async def test_complex_order_refund_runs_supervisor_plan_sequentially_and_summarizes() -> None:
    order_call = ToolCall(
        id="order-call",
        name="get_current_user_order",
        arguments='{"order_number":"EC2026080016"}',
    )
    refund_call = ToolCall(
        id="refund-call",
        name="get_current_user_refund",
        arguments='{"refund_number":"RF2026080001"}',
    )
    model = ScriptedModel(
        "complex",
        ModelTurn(content=None, tool_calls=(order_call,)),
        ModelTurn(content="订单已完成，关联退款单 RF2026080001。", tool_calls=()),
        ModelTurn(content=None, tool_calls=(refund_call,)),
        ModelTurn(content="退款正在处理中。", tool_calls=()),
        plan=("order", "refund"),
        text_response="订单已完成，相关退款正在处理中。",
    )
    tools = RecordingTools()
    graph = build_chat_workflow(model, tools, FakeKnowledge([]))

    updates = await graph_updates(graph, "查询订单和相关退款")
    path = [next(iter(update)) for update in updates]

    assert path == [
        "router",
        "supervisor",
        "order_agent",
        "tools",
        "order_agent",
        "supervisor_step",
        "refund_agent",
        "tools",
        "refund_agent",
        "supervisor_step",
        "supervisor_final",
    ]
    assert tools.calls == [
        ("get_current_user_order", '{"order_number":"EC2026080016"}'),
        ("get_current_user_refund", '{"refund_number":"RF2026080001"}'),
    ]
    assert [call[2] for call in model.route_calls] == [RouteDecision, SupervisorPlan]
    assert updates[5]["supervisor_step"] == {
        "current_step": 1,
        "agent_results": {"order": "订单已完成，关联退款单 RF2026080001。"},
        "tool_used": False,
    }
    assert updates[9]["supervisor_step"]["agent_results"] == {
        "order": "订单已完成，关联退款单 RF2026080001。",
        "refund": "退款正在处理中。",
    }
    assert updates[-1]["supervisor_final"]["messages"][-1]["content"] == (
        "订单已完成，相关退款正在处理中。"
    )
    assert "订单已完成，关联退款单 RF2026080001。" in model.general_calls[-1][1]
    assert "退款正在处理中。" in model.general_calls[-1][1]


@pytest.mark.asyncio
async def test_complex_order_product_uses_the_requested_two_specialists() -> None:
    order_call = ToolCall(
        id="order-call",
        name="get_current_user_order",
        arguments='{"order_number":"EC2026080001"}',
    )
    product_call = ToolCall(
        id="product-call",
        name="get_product_by_sku",
        arguments='{"sku":"ELEC-HUB-001"}',
    )
    model = ScriptedModel(
        "complex",
        ModelTurn(content=None, tool_calls=(order_call,)),
        ModelTurn(content="订单包含 ELEC-HUB-001。", tool_calls=()),
        ModelTurn(content=None, tool_calls=(product_call,)),
        ModelTurn(content="商品售价 299 元。", tool_calls=()),
        plan=("order", "product"),
        text_response="订单商品当前售价 299 元。",
    )
    graph = build_chat_workflow(model, RecordingTools(), FakeKnowledge([]))

    path = await graph_path(graph, "查询订单商品当前价格")

    assert path == [
        "router",
        "supervisor",
        "order_agent",
        "tools",
        "order_agent",
        "supervisor_step",
        "product_agent",
        "tools",
        "product_agent",
        "supervisor_step",
        "supervisor_final",
    ]


@pytest.mark.asyncio
async def test_complex_step_cannot_call_a_later_specialists_tool() -> None:
    wrong_call = ToolCall(
        id="wrong-call",
        name="get_current_user_refund",
        arguments='{"refund_number":"RF2026080001"}',
    )
    tools = RecordingTools()
    graph = build_chat_workflow(
        ScriptedModel(
            "complex",
            ModelTurn(content=None, tool_calls=(wrong_call,)),
            plan=("order", "refund"),
        ),
        tools,
        FakeKnowledge([]),
    )

    with pytest.raises(ModelProviderError):
        await graph_path(graph, "先查询订单再查询退款")

    assert tools.calls == []


@pytest.mark.asyncio
async def test_knowledge_route_answers_from_retrieval_and_appends_source() -> None:
    model = ScriptedModel("knowledge", text_response="平台支持七天无理由退货。")
    knowledge = FakeKnowledge(
        [
            SearchResult(
                chunk_id="refund-1",
                source="refund-policy.md",
                content="符合条件的商品支持签收后七天内申请无理由退货。",
                score=0.88,
            )
        ]
    )
    graph = build_chat_workflow(model, RecordingTools(), knowledge)

    updates = await graph_updates(graph, "退款政策是什么？")

    assert [next(iter(update)) for update in updates] == ["router", "knowledge_agent"]
    answer = updates[-1]["knowledge_agent"]["messages"][-1]["content"]
    assert answer == "平台支持七天无理由退货。\n\n来源：refund-policy.md"
    assert knowledge.questions == ["退款政策是什么？"]
    assert "符合条件的商品支持签收后七天内申请无理由退货。" in model.general_calls[-1][1]


@pytest.mark.asyncio
async def test_knowledge_route_does_not_ask_llm_to_invent_when_retrieval_is_empty() -> None:
    model = ScriptedModel("knowledge")
    graph = build_chat_workflow(model, RecordingTools(), FakeKnowledge([]))

    updates = await graph_updates(graph, "会员生日有什么特殊政策？")

    assert updates[-1]["knowledge_agent"]["messages"][-1]["content"] == (
        "知识库中没有找到足够依据。"
    )
    assert model.general_calls == []


@pytest.mark.asyncio
async def test_complex_order_knowledge_runs_existing_order_agent_then_dense_rag() -> None:
    order_call = ToolCall(
        id="order-call",
        name="get_current_user_order",
        arguments='{"order_number":"EC2026080011"}',
    )
    model = ScriptedModel(
        "complex",
        ModelTurn(content=None, tool_calls=(order_call,)),
        ModelTurn(content="订单配送发生延迟。", tool_calls=()),
        plan=("order", "knowledge"),
        text_responses=(
            "政策规定配送延迟可联系平台协商。",
            "订单发生延迟，可按配送政策联系平台。来源：shipping-policy.md",
        ),
    )
    knowledge = FakeKnowledge(
        [
            SearchResult(
                chunk_id="shipping-1",
                source="shipping-policy.md",
                content="配送延迟时，用户可以联系平台客服协商解决。",
                score=0.84,
            )
        ]
    )
    graph = build_chat_workflow(model, RecordingTools(), knowledge)

    path = await graph_path(graph, "查看订单 EC2026080011，配送延迟时有什么政策？")

    assert path == [
        "router",
        "supervisor",
        "order_agent",
        "tools",
        "order_agent",
        "supervisor_step",
        "knowledge_agent",
        "supervisor_step",
        "supervisor_final",
    ]


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
    graph = build_chat_workflow(model, tools, FakeKnowledge([]))

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
        FakeKnowledge([]),
    )

    with pytest.raises(ModelProviderError):
        await graph_path(graph, "查询订单")

    assert tools.calls == []
