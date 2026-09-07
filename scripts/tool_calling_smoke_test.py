"""Explicitly verify one simple route and one complex Supervisor workflow."""

import asyncio
import json
import sys

from ecommerce_ai_agent.business_tools import BusinessTools
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.database import create_database
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelError
from ecommerce_ai_agent.seed import seed_database
from ecommerce_ai_agent.workflow import CUSTOMER_SERVICE_SYSTEM_PROMPT, build_chat_workflow


class RecordingBusinessTools(BusinessTools):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.calls: list[tuple[str, str, str]] = []

    async def run(self, name: str, arguments: str) -> str:
        result = await super().run(name, arguments)
        self.calls.append((name, arguments, result))
        return result


async def graph_updates(workflow, message: str):
    return [
        update
        async for update in workflow.astream(
            {
                "messages": [
                    {"role": "system", "content": CUSTOMER_SERVICE_SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ]
            },
            stream_mode="updates",
        )
    ]


async def run() -> int:
    settings = Settings()
    if settings.llm_model != "qwen3.8-27b":
        print("LLM_MODEL must be qwen3.8-27b for the M7 smoke test.", file=sys.stderr)
        return 1

    database = create_database(settings)
    model = BailianModel(settings)
    tools = RecordingBusinessTools(database.session_factory, settings.development_user_email)
    workflow = build_chat_workflow(model, tools)
    try:
        async with database.session_factory.begin() as session:
            await seed_database(session)

        simple_updates = await graph_updates(
            workflow,
            "我的订单 EC2026080016 现在是什么状态？",
        )
        simple_path = [next(iter(update)) for update in simple_updates]
        if simple_path != ["router", "order_agent", "tools", "order_agent"]:
            raise RuntimeError(f"simple order request entered path {simple_path}")
        if simple_updates[0]["router"]["route"] != "order":
            raise RuntimeError("simple order request was not routed directly")

        tools.calls.clear()
        complex_updates = await graph_updates(
            workflow,
            "查询订单 EC2026080016，同时告诉我这个订单相关退款现在是什么状态。",
        )
        complex_path = [next(iter(update)) for update in complex_updates]
        expected_path = [
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
        if complex_path != expected_path:
            raise RuntimeError(f"complex request entered path {complex_path}")
        if complex_updates[0]["router"]["route"] != "complex":
            raise RuntimeError("complex request did not enter the Supervisor")
        if complex_updates[1]["supervisor"]["plan"] != ("order", "refund"):
            raise RuntimeError("Supervisor produced an unexpected plan")
        if [call[0] for call in tools.calls] != [
            "get_current_user_order",
            "get_current_user_refund",
        ]:
            raise RuntimeError("Specialists did not execute the expected isolated tools")
        if json.loads(tools.calls[0][1]) != {"order_number": "EC2026080016"}:
            raise RuntimeError("Order Agent supplied unexpected arguments")
        if json.loads(tools.calls[1][1]) != {"refund_number": "RF2026080001"}:
            raise RuntimeError("Refund Agent did not use the related refund number")
        if not all(json.loads(call[2]).get("found") is True for call in tools.calls):
            raise RuntimeError("A Specialist did not receive owned business data")
        final_content = complex_updates[-1]["supervisor_final"]["messages"][-1]["content"]
        if not final_content:
            raise RuntimeError("Supervisor returned an empty final answer")
    except (ModelError, RuntimeError, ValueError) as exc:
        code = exc.code if isinstance(exc, ModelError) else type(exc).__name__
        print(f"M7 Supervisor smoke failed: {code}: {exc}", file=sys.stderr)
        return 1
    finally:
        await model.close()
        await database.engine.dispose()

    print(
        f"M7 Supervisor smoke passed: model={settings.llm_model}, "
        "paths=simple_order,complex_order_refund"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
