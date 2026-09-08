import json
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ecommerce_ai_agent.llm.client import ModelTurn, ToolCall
from ecommerce_ai_agent.workflow import build_chat_workflow


class RefundRequestModel:
    async def generate_structured(self, system_prompt, user_prompt, schema_type):
        return schema_type(route="refund")

    async def generate_turn(self, messages, tools) -> ModelTurn:
        return ModelTurn(
            content=None,
            tool_calls=(
                ToolCall(
                    id="request-refund",
                    name="request_refund",
                    arguments=json.dumps(
                        {
                            "order_number": "EC2026080021",
                            "amount": "150.00",
                            "reason": "配送延迟",
                        }
                    ),
                ),
            ),
        )


class ReviewTools:
    def __init__(self) -> None:
        self.decisions: list[tuple] = []

    async def request_refund(self, arguments, user_id, thread_id) -> str:
        return json.dumps(
            {
                "outcome": "pending_review",
                "refund_number": "RF-NEW",
                "review_id": "0c283214-67ed-4864-bcab-6c7ca1367d7c",
                "thread_id": thread_id,
            }
        )

    async def resolve_refund_review(self, review_id, approve, reviewer_id, note) -> str:
        self.decisions.append((review_id, approve, reviewer_id, note))
        return json.dumps(
            {"outcome": "approved" if approve else "rejected", "refund_number": "RF-NEW"}
        )

    async def run(self, name, arguments, user_id) -> str:
        raise AssertionError("write workflow should use request_refund")


class EmptyKnowledge:
    async def search(self, question):
        return []


@pytest.mark.parametrize(("decision", "expected"), [("approve", "已通过"), ("reject", "未通过")])
@pytest.mark.asyncio
async def test_refund_review_interrupt_resumes_with_human_decision(decision, expected) -> None:
    user_id = uuid4()
    reviewer_id = uuid4()
    thread_id = f"{user_id}:{uuid4()}"
    tools = ReviewTools()
    graph = build_chat_workflow(
        RefundRequestModel(),
        tools,
        EmptyKnowledge(),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": thread_id}}

    paused = await graph.ainvoke(
        {
            "messages": [{"role": "user", "content": "申请退款150元"}],
            "user_id": str(user_id),
            "tool_used": False,
        },
        config,
    )
    resumed = await graph.ainvoke(
        Command(
            resume={
                "decision": decision,
                "reviewer_id": str(reviewer_id),
                "note": "人工决定",
            }
        ),
        config,
    )

    assert paused["__interrupt__"][0].value["refund_number"] == "RF-NEW"
    assert expected in resumed["messages"][-1]["content"]
    assert len(tools.decisions) == 1
