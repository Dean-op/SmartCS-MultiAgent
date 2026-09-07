from operator import add
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from ecommerce_ai_agent.business_tools import TOOL_DEFINITIONS, BusinessTools
from ecommerce_ai_agent.llm.client import BailianModel, ModelTurn
from ecommerce_ai_agent.llm.errors import ModelProviderError
from ecommerce_ai_agent.llm.schemas import RouteDecision, RouteName

ROUTER_PROMPT = """将用户消息分类为且仅分类为一个 route：
order：订单状态、订单商品或物流；refund：退款记录或退款进度；
product：商品、SKU、价格或商品信息；general：问候或不需要业务数据的问题。
复杂请求只选择当前最主要的一个意图。不要回答用户问题。"""

CUSTOMER_SERVICE_SYSTEM_PROMPT = """你是一名简洁、诚实的电商客服。
回答普通问题，但不要声称查询或修改了真实业务数据。"""

ORDER_AGENT_PROMPT = """你是订单查询客服，只处理当前用户的订单、订单项和物流问题。
需要真实数据时只使用订单查询工具，只能根据工具结果回答，不得编造或执行写操作。"""

REFUND_AGENT_PROMPT = """你是退款查询客服，只处理当前用户已有退款记录和进度问题。
需要真实数据时只使用退款查询工具，只能根据工具结果回答，不得创建或修改退款。"""

PRODUCT_AGENT_PROMPT = """你是商品查询客服，只处理 SKU、商品信息和价格问题。
需要真实数据时只使用商品查询工具，只能根据工具结果回答，不得编造商品信息。"""

ORDER_TOOLS = [TOOL_DEFINITIONS[0]]
PRODUCT_TOOLS = [TOOL_DEFINITIONS[1]]
REFUND_TOOLS = [TOOL_DEFINITIONS[2]]


class ChatState(TypedDict):
    messages: Annotated[list[dict[str, Any]], add]
    route: NotRequired[RouteName]


def _user_message(state: ChatState) -> str:
    return next(
        message["content"]
        for message in reversed(state["messages"])
        if message.get("role") == "user"
    )


def _agent_messages(state: ChatState, prompt: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": prompt},
        *(message for message in state["messages"] if message.get("role") != "system"),
    ]


def _assistant_message(state: ChatState, turn: ModelTurn) -> dict[str, Any]:
    if turn.tool_calls and any(message.get("role") == "tool" for message in state["messages"]):
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


def build_chat_workflow(model: BailianModel, tools: BusinessTools):
    async def router(state: ChatState) -> dict[str, RouteName]:
        decision = await model.generate_structured(
            ROUTER_PROMPT,
            _user_message(state),
            RouteDecision,
        )
        return {"route": decision.route}

    async def general_agent(state: ChatState) -> ChatState:
        content = await model.generate_text(
            CUSTOMER_SERVICE_SYSTEM_PROMPT,
            _user_message(state),
        )
        return {"messages": [{"role": "assistant", "content": content}]}

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

    async def tool_node(state: ChatState) -> ChatState:
        match state["route"]:
            case "order":
                allowed_tool = "get_current_user_order"
            case "refund":
                allowed_tool = "get_current_user_refund"
            case "product":
                allowed_tool = "get_product_by_sku"
            case _:
                raise ModelProviderError

        calls = state["messages"][-1]["tool_calls"]
        if any(call["function"]["name"] != allowed_tool for call in calls):
            raise ModelProviderError
        return {
            "messages": [
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": await tools.run(
                        call["function"]["name"],
                        call["function"]["arguments"],
                    ),
                }
                for call in calls
            ]
        }

    def route_after_router(state: ChatState) -> RouteName:
        return state["route"]

    def route_after_agent(state: ChatState) -> Literal["tools", "__end__"]:
        return "tools" if state["messages"][-1].get("tool_calls") else END

    def route_after_tools(
        state: ChatState,
    ) -> Literal["order_agent", "refund_agent", "product_agent"]:
        match state["route"]:
            case "order":
                return "order_agent"
            case "refund":
                return "refund_agent"
            case "product":
                return "product_agent"
            case _:
                raise ModelProviderError

    builder = StateGraph(ChatState)
    builder.add_node("router", router)
    builder.add_node("order_agent", order_agent)
    builder.add_node("refund_agent", refund_agent)
    builder.add_node("product_agent", product_agent)
    builder.add_node("general_agent", general_agent)
    builder.add_node("tools", tool_node)
    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        route_after_router,
        {
            "order": "order_agent",
            "refund": "refund_agent",
            "product": "product_agent",
            "general": "general_agent",
        },
    )
    for agent in ("order_agent", "refund_agent", "product_agent"):
        builder.add_conditional_edges(agent, route_after_agent)
    builder.add_edge("general_agent", END)
    builder.add_conditional_edges("tools", route_after_tools)
    return builder.compile()
