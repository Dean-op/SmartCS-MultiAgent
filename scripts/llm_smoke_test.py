"""Explicitly call Bailian for text and structured-output verification."""

import asyncio
import sys
from time import perf_counter

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelError
from ecommerce_ai_agent.llm.schemas import MessageAssessment
from ecommerce_ai_agent.workflow import CUSTOMER_SERVICE_SYSTEM_PROMPT

ASSESSMENT_PROMPT = """判断客户消息是否必须访问真实账户、订单、物流或退款数据才能完成。
返回简短摘要、是否需要真实业务操作以及判断原因。"""


async def run() -> int:
    settings = Settings()
    if settings.llm_model != "qwen3.8-27b":
        print("LLM_MODEL must be qwen3.8-27b for the M3 smoke test.", file=sys.stderr)
        return 1

    started_at = perf_counter()
    try:
        model = BailianModel(settings)
        try:
            text = await model.generate_text(
                CUSTOMER_SERVICE_SYSTEM_PROMPT,
                "请用一句话说明申请售后前通常需要准备哪些信息。",
            )
            assessment = await model.generate_structured(
                ASSESSMENT_PROMPT,
                "请帮我查询订单 A1001 的物流状态。",
                MessageAssessment,
            )
        finally:
            await model.close()
    except ModelError as exc:
        print(f"M3 LLM smoke failed: {exc.code}", file=sys.stderr)
        return 1

    elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
    print(
        "M3 LLM smoke passed: "
        f"model={settings.llm_model}, text_chars={len(text)}, "
        f"structured_type={type(assessment).__name__}, "
        f"requires_business_action={assessment.requires_business_action}, "
        f"summary_chars={len(assessment.summary)}, elapsed_ms={elapsed_ms}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
