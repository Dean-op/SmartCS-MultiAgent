"""Verify real LLM multi-turn context with the PostgreSQL checkpointer."""

import asyncio
import json
import sys
from uuid import uuid4

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


class RecordingBusinessTools(BusinessTools):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.calls: list[tuple[str, str]] = []

    async def run(self, name: str, arguments: str, user_id) -> str:
        self.calls.append((name, arguments))
        return await super().run(name, arguments, user_id)


async def run() -> int:
    settings = Settings()
    database = create_database(settings)
    model = BailianModel(settings)
    knowledge = KnowledgeBase(settings, model)
    user_id = seed_id("user:alice@example.com")
    tools = RecordingBusinessTools(database.session_factory)
    dsn = build_checkpoint_url(settings).render_as_string(hide_password=False)
    try:
        async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer:
            await checkpointer.setup()
            service = ChatService(
                model,
                tools,
                knowledge,
                checkpointer=checkpointer,
            )

            first = await service.respond(ChatRequest(message="查询订单 EC2026080016"), user_id)
            conversation_id = first.conversation_id

            tools.calls.clear()
            await service.respond(
                ChatRequest(
                    message="它现在是什么状态？",
                    conversation_id=conversation_id,
                ),
                user_id,
            )
            if not (
                len(tools.calls) == 1
                and tools.calls[0][0] == "get_current_user_order"
                and json.loads(tools.calls[0][1]) == {"order_number": "EC2026080016"}
            ):
                raise RuntimeError(f"order follow-up produced unexpected tool calls: {tools.calls}")

            tools.calls.clear()
            await service.respond(
                ChatRequest(
                    message="它有没有退款记录？",
                    conversation_id=conversation_id,
                ),
                user_id,
            )
            if not (
                len(tools.calls) == 1
                and tools.calls[0][0] == "get_current_user_refund"
                and json.loads(tools.calls[0][1]) == {"refund_number": "RF2026080001"}
            ):
                raise RuntimeError(
                    f"cross-agent follow-up produced unexpected tool calls: {tools.calls}"
                )

            tools.calls.clear()
            await service.respond(
                ChatRequest(
                    message="它现在是什么状态？",
                    conversation_id=uuid4(),
                ),
                user_id,
            )
            leaked = any(
                private_id in json.dumps(tools.calls, ensure_ascii=False)
                for private_id in ("EC2026080016", "RF2026080001")
            )
            if leaked:
                raise RuntimeError("conversation context leaked into another thread")
    except (ModelError, RuntimeError, ValueError) as exc:
        code = exc.code if isinstance(exc, ModelError) else type(exc).__name__
        print(f"M10 conversation smoke failed: {code}: {exc}", file=sys.stderr)
        return 1
    finally:
        await knowledge.close()
        await model.close()
        await database.engine.dispose()

    print("M10 conversation smoke passed: order_follow_up,cross_agent,isolation")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        raise SystemExit(asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop))
    raise SystemExit(asyncio.run(run()))
