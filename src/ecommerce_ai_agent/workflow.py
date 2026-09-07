from operator import add
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from ecommerce_ai_agent.business_tools import TOOL_DEFINITIONS, BusinessTools
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelProviderError

CUSTOMER_SERVICE_SYSTEM_PROMPT = """你是一名简洁、诚实的电商智能客服。
你可以回答一般性问题，也可以使用提供的只读工具查询当前用户的订单、商品和退款。
涉及订单、商品价格或退款状态时应先调用相应工具，只能使用工具返回的数据回答。
工具返回 found=false 时，说明未找到记录或该记录不属于当前用户，不要猜测。
当前不能修改订单或数据库，也不能创建退款；用户要求写操作时应明确无法执行。
不要编造订单状态、物流、价格、退款状态或操作结果。"""


class ChatState(TypedDict):
    messages: Annotated[list[dict[str, Any]], add]


def build_chat_workflow(model: BailianModel, tools: BusinessTools):
    async def model_node(state: ChatState) -> ChatState:
        turn = await model.generate_turn(state["messages"], TOOL_DEFINITIONS)
        if turn.tool_calls and any(message.get("role") == "tool" for message in state["messages"]):
            raise ModelProviderError
        return {
            "messages": [
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
            ]
        }

    async def tool_node(state: ChatState) -> ChatState:
        calls = state["messages"][-1]["tool_calls"]
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

    def route_after_model(state: ChatState) -> Literal["tools", "__end__"]:
        return "tools" if state["messages"][-1]["tool_calls"] else END

    builder = StateGraph(ChatState)
    builder.add_node("model", model_node)
    builder.add_node("tools", tool_node)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", route_after_model)
    builder.add_edge("tools", "model")
    return builder.compile()
