"""Embed local Markdown policies and upsert them into Milvus."""

import asyncio
import sys
from pathlib import Path

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.knowledge import KnowledgeBase, chunk_markdown_documents
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelError

KNOWLEDGE_DIRECTORY = Path(__file__).resolve().parents[1] / "knowledge"


async def run() -> int:
    settings = Settings()
    model = BailianModel(settings)
    knowledge = KnowledgeBase(settings, model)
    try:
        chunks = await asyncio.to_thread(chunk_markdown_documents, KNOWLEDGE_DIRECTORY)
        count = await knowledge.ingest(chunks)
    except ModelError as exc:
        print(f"Knowledge ingestion failed: {exc.code}", file=sys.stderr)
        return 1
    finally:
        await knowledge.close()
        await model.close()

    print(
        f"Knowledge ingestion complete: collection={settings.knowledge_collection}, "
        f"documents=4, chunks={count}, dimensions={settings.embedding_dimensions}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
