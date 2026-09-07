"""Explicitly verify real Dense Retrieval and the Knowledge Agent."""

import asyncio
import sys

from ecommerce_ai_agent.business_tools import BusinessTools
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.database import create_database
from ecommerce_ai_agent.knowledge import KnowledgeBase
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelError
from ecommerce_ai_agent.workflow import CUSTOMER_SERVICE_SYSTEM_PROMPT, build_chat_workflow


async def run() -> int:
    settings = Settings()
    database = create_database(settings)
    model = BailianModel(settings)
    knowledge = KnowledgeBase(settings, model)
    workflow = build_chat_workflow(
        model,
        BusinessTools(database.session_factory, settings.development_user_email),
        knowledge,
    )
    try:
        question = "配送延迟是否会自动符合退款条件？"
        results = await knowledge.search(question)
        if not results or results[0].source not in {
            "refund-policy.md",
            "shipping-policy.md",
        }:
            raise RuntimeError("Dense Retrieval did not return a relevant policy source")

        updates = [
            update
            async for update in workflow.astream(
                {
                    "messages": [
                        {"role": "system", "content": CUSTOMER_SERVICE_SYSTEM_PROMPT},
                        {"role": "user", "content": question},
                    ]
                },
                stream_mode="updates",
            )
        ]
        path = [next(iter(update)) for update in updates]
        if path != ["router", "knowledge_agent"]:
            raise RuntimeError(f"Knowledge question entered path {path}")
        answer = updates[-1]["knowledge_agent"]["messages"][-1]["content"]
        if "来源：" not in answer:
            raise RuntimeError("Knowledge Agent answer did not include sources")
    except (ModelError, RuntimeError, ValueError) as exc:
        code = exc.code if isinstance(exc, ModelError) else type(exc).__name__
        print(f"M8 Dense RAG smoke failed: {code}: {exc}", file=sys.stderr)
        return 1
    finally:
        await knowledge.close()
        await model.close()
        await database.engine.dispose()

    sources = ",".join(result.source for result in results)
    print(
        f"M8 Dense RAG smoke passed: embedding={settings.embedding_model}, "
        f"dimensions={settings.embedding_dimensions}, top_k={len(results)}, sources={sources}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
