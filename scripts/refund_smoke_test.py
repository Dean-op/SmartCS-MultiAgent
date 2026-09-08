"""Explicit real-model smoke for refund write and HITL resume."""

import asyncio
import json
import sys
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from ecommerce_ai_agent.business_tools import BusinessTools
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.database import build_checkpoint_url, create_database
from ecommerce_ai_agent.knowledge import KnowledgeBase
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelError
from ecommerce_ai_agent.schemas.chat import ChatRequest
from ecommerce_ai_agent.seed import seed_id
from ecommerce_ai_agent.services.chat import ChatService
from ecommerce_ai_agent.services.refund import RefundService

CONVERSATION_ID = UUID("70de1a07-30e0-42d0-a011-000000000011")


class RecordingBusinessTools(BusinessTools):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.refund_results: list[dict] = []

    async def request_refund(self, arguments, user_id, thread_id) -> str:
        result = await super().request_refund(arguments, user_id, thread_id)
        self.refund_results.append(json.loads(result))
        return result


async def run() -> int:
    settings = Settings()
    database = create_database(settings)
    model = BailianModel(settings)
    knowledge = KnowledgeBase(settings, model)
    tools = RecordingBusinessTools(database.session_factory, settings)
    customer_id = seed_id("user:alice@example.com")
    admin_id = seed_id("user:admin@example.com")
    thread_id = f"{customer_id}:{CONVERSATION_ID}"
    dsn = build_checkpoint_url(settings).render_as_string(hide_password=False)
    try:
        async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer:
            await checkpointer.setup()
            service = ChatService(model, tools, knowledge, checkpointer=checkpointer)
            response = await service.respond(
                ChatRequest(
                    message=(
                        "请为我的订单 EC2026080021 申请退款 150 元，"
                        "原因是商品到货后发现明显质量问题。"
                    ),
                    conversation_id=CONVERSATION_ID,
                ),
                customer_id,
            )
            if not tools.refund_results:
                raise RuntimeError("Refund Agent did not call request_refund")
            result = tools.refund_results[-1]
            if result["outcome"] == "pending_review":
                resumed = await service.resume_review(
                    thread_id,
                    CONVERSATION_ID,
                    "approve",
                    admin_id,
                    "M11 real smoke approval",
                )
                if "已通过人工审核并完成" not in resumed.message.content:
                    raise RuntimeError("Approved workflow did not return a completion result")
            elif result["outcome"] != "duplicate":
                raise RuntimeError(f"Unexpected refund outcome: {result['outcome']}")

            async with database.session_factory() as session:
                review = await RefundService(session).get_review(UUID(result["review_id"]))
            if review is None or review.status.value != "approved":
                raise RuntimeError("Refund review was not persisted as approved")
            if response.conversation_id != CONVERSATION_ID:
                raise RuntimeError("Conversation identifier changed")
    except (ModelError, RuntimeError, ValueError) as exc:
        code = exc.code if isinstance(exc, ModelError) else type(exc).__name__
        print(f"M11 refund smoke failed: {code}: {exc}", file=sys.stderr)
        return 1
    finally:
        await knowledge.close()
        await model.close()
        await database.engine.dispose()

    print("M11 refund smoke passed: real_llm,write,interrupt,approve,resume")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        raise SystemExit(asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop))
    raise SystemExit(asyncio.run(run()))
