"""Explicitly verify Bailian Tool Calling against seeded PostgreSQL data."""

import asyncio
import json
import sys
from dataclasses import dataclass

from ecommerce_ai_agent.business_tools import BusinessTools
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.database import create_database
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelError
from ecommerce_ai_agent.seed import seed_database
from ecommerce_ai_agent.workflow import CUSTOMER_SERVICE_SYSTEM_PROMPT, build_chat_workflow


@dataclass(frozen=True)
class Scenario:
    message: str
    route: str
    tool_name: str | None
    argument_name: str | None = None
    argument_value: str | None = None
    expected_found: bool | None = None


class RecordingBusinessTools(BusinessTools):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.calls: list[tuple[str, str, str]] = []

    async def run(self, name: str, arguments: str) -> str:
        result = await super().run(name, arguments)
        self.calls.append((name, arguments, result))
        return result


SCENARIOS = (
    Scenario(
        "我的订单 EC2026080016 现在是什么状态？",
        "order",
        "get_current_user_order",
        "order_number",
        "EC2026080016",
        True,
    ),
    Scenario(
        "SKU ELEC-HUB-001 这个商品多少钱？",
        "product",
        "get_product_by_sku",
        "sku",
        "ELEC-HUB-001",
        True,
    ),
    Scenario(
        "退款单 RF2026080001 现在处理到哪了？",
        "refund",
        "get_current_user_refund",
        "refund_number",
        "RF2026080001",
        True,
    ),
    Scenario(
        "我的订单 EC2026080002 现在是什么状态？",
        "order",
        "get_current_user_order",
        "order_number",
        "EC2026080002",
        False,
    ),
    Scenario("你好", "general", None),
)


async def run() -> int:
    settings = Settings()
    if settings.llm_model != "qwen3.8-27b":
        print("LLM_MODEL must be qwen3.8-27b for the M6 smoke test.", file=sys.stderr)
        return 1

    database = create_database(settings)
    model = BailianModel(settings)
    tools = RecordingBusinessTools(database.session_factory, settings.development_user_email)
    workflow = build_chat_workflow(model, tools)
    passed: list[str] = []
    try:
        async with database.session_factory.begin() as session:
            await seed_database(session)

        for scenario in SCENARIOS:
            tools.calls.clear()
            updates = [
                update
                async for update in workflow.astream(
                    {
                        "messages": [
                            {"role": "system", "content": CUSTOMER_SERVICE_SYSTEM_PROMPT},
                            {"role": "user", "content": scenario.message},
                        ]
                    },
                    stream_mode="updates",
                )
            ]
            path = [next(iter(update)) for update in updates]
            selected_route = updates[0]["router"]["route"]
            agent_node = f"{scenario.route}_agent"
            final_content = updates[-1][agent_node]["messages"][-1]["content"]
            if not final_content:
                raise RuntimeError("model returned an empty final answer")
            if selected_route != scenario.route:
                raise RuntimeError("router selected an unexpected route")

            if scenario.tool_name is None:
                if path != ["router", "general_agent"]:
                    raise RuntimeError("ordinary greeting followed an unexpected graph path")
                if tools.calls:
                    raise RuntimeError("ordinary greeting unexpectedly called a tool")
                passed.append("no_tool")
                continue

            if path != ["router", agent_node, "tools", agent_node]:
                raise RuntimeError("tool scenario followed an unexpected graph path")
            if len(tools.calls) != 1:
                raise RuntimeError("scenario did not execute exactly one tool")
            name, raw_arguments, raw_result = tools.calls[0]
            arguments = json.loads(raw_arguments)
            result = json.loads(raw_result)
            if name != scenario.tool_name:
                raise RuntimeError("model selected the wrong tool")
            if arguments != {scenario.argument_name: scenario.argument_value}:
                raise RuntimeError("model supplied unexpected tool arguments")
            if result.get("found") is not scenario.expected_found:
                raise RuntimeError("tool result did not match the expected ownership")
            passed.append(name if scenario.expected_found else "ownership")
    except (ModelError, RuntimeError, ValueError) as exc:
        code = exc.code if isinstance(exc, ModelError) else type(exc).__name__
        print(f"M6 Router smoke failed: {code}", file=sys.stderr)
        return 1
    finally:
        await model.close()
        await database.engine.dispose()

    print(f"M6 Router smoke passed: model={settings.llm_model}, scenarios={','.join(passed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
