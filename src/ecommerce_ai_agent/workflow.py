import json
from operator import add
from typing import Annotated, Any, Literal, NotRequired, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ecommerce_ai_agent.business_tools import TOOL_DEFINITIONS, BusinessTools
from ecommerce_ai_agent.knowledge import KnowledgeBase
from ecommerce_ai_agent.llm.client import BailianModel, ModelTurn
from ecommerce_ai_agent.llm.errors import ModelProviderError
from ecommerce_ai_agent.llm.schemas import (
    RouteDecision,
    RouteName,
    SpecialistRoute,
    SupervisorPlan,
)

ROUTER_PROMPT = """将用户消息分类为且仅分类为一个 route：
order：订单状态、订单商品或物流；refund：退款记录或退款进度；
product：商品、SKU、价格或商品信息；knowledge：退款、配送、售后、支付等企业政策；
general：问候或不需要业务数据的问题；
complex：必须由两个或更多 Specialist 顺序协作才能完成的问题。
退款单进度属于 refund，退款规则属于 knowledge。
简单请求不能选择 complex。不要回答用户问题。"""

SUPERVISOR_PLAN_PROMPT = """为复杂请求生成最小顺序执行计划。
steps 只能包含 order、refund、product、knowledge，至少两个且不能重复。
存在依赖时把提供信息的 Specialist 放在前面，例如先查订单再查关联退款。
不要回答用户问题，也不要调用任何工具。"""

SUPERVISOR_FINAL_PROMPT = """你是客服协调员。根据各 Specialist 的已验证结果，
简洁汇总回答原始问题并保留来源信息。不要补充结果中不存在的事实，不要声称执行写操作。"""

CUSTOMER_SERVICE_SYSTEM_PROMPT = """你是一名简洁、诚实的电商客服。
回答普通问题，但不要声称查询或修改了真实业务数据。"""

ORDER_AGENT_PROMPT = """你是订单查询客服，只处理当前用户的订单、订单项和物流问题。
每次用户询问订单当前状态时，只要消息或历史中有订单号，就必须调用订单查询工具刷新。
只能根据工具结果回答，不得编造或执行写操作。"""

REFUND_AGENT_PROMPT = """你是退款客服，处理退款查询和退款申请。
用户明确要求退款时，提取订单号、可选金额和原因，并调用 request_refund。
只要用户消息或前序结果中有退款单号，就必须使用退款查询工具确认最新状态。
资格、合法金额、风险和审批完全由工具决定，不得自行判断或绕过人工审核。"""

PRODUCT_AGENT_PROMPT = """你是商品查询客服，只处理 SKU、商品信息和价格问题。
需要真实数据时只使用商品查询工具，只能根据工具结果回答，不得编造商品信息。"""

KNOWLEDGE_AGENT_PROMPT = """你是企业政策知识库客服。
只能根据提供的知识库片段回答；片段没有依据的内容不得猜测或补充。"""

ORDER_TOOLS = [TOOL_DEFINITIONS[0]]
PRODUCT_TOOLS = [TOOL_DEFINITIONS[1]]
REFUND_TOOLS = [TOOL_DEFINITIONS[2], TOOL_DEFINITIONS[3]]


class ChatState(TypedDict):
    messages: Annotated[list[dict[str, Any]], add]
    route: NotRequired[RouteName]
    plan: NotRequired[tuple[SpecialistRoute, ...]]
    current_step: NotRequired[int]
    agent_results: NotRequired[dict[SpecialistRoute, str]]
    tool_used: NotRequired[bool]
    user_id: NotRequired[str]
    pending_review: NotRequired[dict[str, str] | None]


def _user_message(state: ChatState) -> str:
    return next(
        message["content"]
        for message in reversed(state["messages"])
        if message.get("role") == "user"
    )


def _router_context(state: ChatState) -> str:
    return "\n".join(
        f"{message.get('role')}: {message.get('content')}" for message in state["messages"]
    )


def _agent_messages(state: ChatState, prompt: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": prompt},
        *(message for message in state["messages"] if message.get("role") != "system"),
    ]


def _assistant_message(state: ChatState, turn: ModelTurn) -> dict[str, Any]:
    if turn.tool_calls and state.get("tool_used", False):
        raise ModelProviderError
    return {
        "role": "assistant",
        "content": turn.content,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in turn.tool_calls
        ],
    }


def _active_specialist(state: ChatState) -> SpecialistRoute:
    route = state["route"]
    if route == "complex":
        return state["plan"][state["current_step"]]
    if route in ("order", "refund", "product", "knowledge"):
        return route
    raise ModelProviderError


def build_chat_workflow(
    model: BailianModel,
    tools: BusinessTools,
    knowledge: KnowledgeBase,
    *,
    checkpointer: Any | None = None,
):
    async def router(state: ChatState) -> dict[str, RouteName]:
        decision = await model.generate_structured(
            ROUTER_PROMPT,
            _router_context(state),
            RouteDecision,
        )
        return {"route": decision.route}

    async def general_agent(state: ChatState) -> ChatState:
        content = await model.generate_text(
            CUSTOMER_SERVICE_SYSTEM_PROMPT,
            _user_message(state),
        )
        return {"messages": [{"role": "assistant", "content": content}]}

    async def supervisor(state: ChatState) -> ChatState:
        plan = await model.generate_structured(
            SUPERVISOR_PLAN_PROMPT,
            _user_message(state),
            SupervisorPlan,
        )
        return {
            "plan": plan.steps,
            "current_step": 0,
            "agent_results": {},
            "tool_used": False,
        }

    async def order_agent(state: ChatState) -> ChatState:
        turn = await model.generate_turn(
            _agent_messages(state, ORDER_AGENT_PROMPT),
            ORDER_TOOLS,
        )
        return {"messages": [_assistant_message(state, turn)]}

    async def refund_agent(state: ChatState) -> ChatState:
        turn = await model.generate_turn(
            _agent_messages(state, REFUND_AGENT_PROMPT),
            REFUND_TOOLS,
        )
        return {"messages": [_assistant_message(state, turn)]}

    async def product_agent(state: ChatState) -> ChatState:
        turn = await model.generate_turn(
            _agent_messages(state, PRODUCT_AGENT_PROMPT),
            PRODUCT_TOOLS,
        )
        return {"messages": [_assistant_message(state, turn)]}

    async def knowledge_agent(state: ChatState) -> ChatState:
        results = await knowledge.search(_user_message(state))
        if not results:
            return {"messages": [{"role": "assistant", "content": "知识库中没有找到足够依据。"}]}
        context = "\n\n".join(
            f"[{result.source}#{result.chunk_id}]\n{result.content}" for result in results
        )
        answer = await model.generate_text(
            KNOWLEDGE_AGENT_PROMPT,
            f"问题：{_user_message(state)}\n\n知识库片段：\n{context}",
        )
        sources = "、".join(dict.fromkeys(result.source for result in results))
        return {"messages": [{"role": "assistant", "content": f"{answer}\n\n来源：{sources}"}]}

    async def tool_node(state: ChatState, config: RunnableConfig) -> ChatState:
        match _active_specialist(state):
            case "order":
                allowed_tools = {"get_current_user_order"}
            case "refund":
                allowed_tools = {"get_current_user_refund", "request_refund"}
            case "product":
                allowed_tools = {"get_product_by_sku"}
            case _:
                raise ModelProviderError

        calls = state["messages"][-1]["tool_calls"]
        if any(call["function"]["name"] not in allowed_tools for call in calls):
            raise ModelProviderError
        messages = []
        pending_review = None
        for call in calls:
            name = call["function"]["name"]
            if name == "request_refund":
                content = await tools.request_refund(
                    call["function"]["arguments"],
                    UUID(state["user_id"]),
                    config["configurable"]["thread_id"],
                )
                payload = json.loads(content)
                if payload.get("outcome") == "pending_review":
                    pending_review = {
                        "review_id": payload["review_id"],
                        "refund_number": payload["refund_number"],
                        "thread_id": payload["thread_id"],
                    }
            else:
                content = await tools.run(
                    name,
                    call["function"]["arguments"],
                    UUID(state["user_id"]),
                )
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        return {
            "messages": messages,
            "tool_used": True,
            "pending_review": pending_review,
        }

    async def human_review(state: ChatState) -> ChatState:
        pending = state["pending_review"]
        if not pending:
            raise ModelProviderError
        decision = interrupt(pending)
        approve = decision["decision"] == "approve"
        result = await tools.resolve_refund_review(
            UUID(pending["review_id"]),
            approve,
            UUID(decision["reviewer_id"]),
            decision.get("note"),
        )
        resolved = json.loads(result)
        if resolved.get("outcome") == "approved":
            content = f"退款 {resolved['refund_number']} 已通过人工审核并完成。"
        elif resolved.get("outcome") == "rejected":
            content = f"退款 {resolved['refund_number']} 未通过人工审核，未执行退款。"
        else:
            raise ModelProviderError
        return {
            "messages": [{"role": "assistant", "content": content}],
            "pending_review": None,
        }

    async def supervisor_step(state: ChatState) -> ChatState:
        content = state["messages"][-1].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelProviderError
        results = dict(state["agent_results"])
        results[_active_specialist(state)] = content.strip()
        return {
            "current_step": state["current_step"] + 1,
            "agent_results": results,
            "tool_used": False,
        }

    async def supervisor_final(state: ChatState) -> ChatState:
        results = "\n".join(
            f"{agent}: {result}" for agent, result in state["agent_results"].items()
        )
        content = await model.generate_text(
            SUPERVISOR_FINAL_PROMPT,
            f"原始请求：{_user_message(state)}\nSpecialist 结果：\n{results}",
        )
        return {"messages": [{"role": "assistant", "content": content}]}

    def route_after_router(state: ChatState) -> RouteName:
        return state["route"]

    def route_after_agent(
        state: ChatState,
    ) -> Literal["tools", "supervisor_step", "__end__"]:
        if state["messages"][-1].get("tool_calls"):
            return "tools"
        return "supervisor_step" if state["route"] == "complex" else END

    def route_to_active_specialist(
        state: ChatState,
    ) -> Literal["order_agent", "refund_agent", "product_agent", "knowledge_agent"]:
        match _active_specialist(state):
            case "order":
                return "order_agent"
            case "refund":
                return "refund_agent"
            case "product":
                return "product_agent"
            case "knowledge":
                return "knowledge_agent"
            case _:
                raise ModelProviderError

    def route_after_tools_or_review(
        state: ChatState,
    ) -> Literal[
        "human_review",
        "order_agent",
        "refund_agent",
        "product_agent",
        "knowledge_agent",
    ]:
        if state.get("pending_review"):
            return "human_review"
        return route_to_active_specialist(state)

    def route_after_step(
        state: ChatState,
    ) -> Literal[
        "order_agent",
        "refund_agent",
        "product_agent",
        "knowledge_agent",
        "supervisor_final",
    ]:
        if state["current_step"] == len(state["plan"]):
            return "supervisor_final"
        return route_to_active_specialist(state)

    builder = StateGraph(ChatState)
    builder.add_node("router", router)
    builder.add_node("order_agent", order_agent)
    builder.add_node("refund_agent", refund_agent)
    builder.add_node("product_agent", product_agent)
    builder.add_node("knowledge_agent", knowledge_agent)
    builder.add_node("general_agent", general_agent)
    builder.add_node("supervisor", supervisor)
    builder.add_node("supervisor_step", supervisor_step)
    builder.add_node("supervisor_final", supervisor_final)
    builder.add_node("tools", tool_node)
    builder.add_node("human_review", human_review)
    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        route_after_router,
        {
            "order": "order_agent",
            "refund": "refund_agent",
            "product": "product_agent",
            "knowledge": "knowledge_agent",
            "general": "general_agent",
            "complex": "supervisor",
        },
    )
    for agent in ("order_agent", "refund_agent", "product_agent", "knowledge_agent"):
        builder.add_conditional_edges(agent, route_after_agent)
    builder.add_edge("general_agent", END)
    builder.add_conditional_edges("supervisor", route_to_active_specialist)
    builder.add_conditional_edges("tools", route_after_tools_or_review)
    builder.add_conditional_edges("supervisor_step", route_after_step)
    builder.add_edge("supervisor_final", END)
    builder.add_edge("human_review", END)
    return builder.compile(checkpointer=checkpointer)
