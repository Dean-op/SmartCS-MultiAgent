"""Embed local Markdown policies and upsert them into Milvus."""

import asyncio
import sys

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.database import create_database
from ecommerce_ai_agent.knowledge import KnowledgeBase, chunk_markdown_text
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelError
from ecommerce_ai_agent.services.knowledge_documents import KnowledgeDocumentService


async def run() -> int:
    settings = Settings()
    database = create_database(settings)
    model = BailianModel(settings)
    knowledge = KnowledgeBase(settings, model)
    try:
        async with database.session_factory() as session:
            documents = await KnowledgeDocumentService(session).list()
        chunks = [
            chunk
            for document in documents
            for chunk in chunk_markdown_text(document.source, document.content)
        ]
        count = await knowledge.ingest(chunks, rebuild=True)
        async with database.session_factory.begin() as session:
            await KnowledgeDocumentService(session).mark_all_indexed()
    except ModelError as exc:
        print(f"Knowledge ingestion failed: {exc.code}", file=sys.stderr)
        return 1
    finally:
        await knowledge.close()
        await model.close()
        await database.engine.dispose()

    print(
        f"Knowledge ingestion complete: collection={settings.knowledge_collection}, "
        f"documents={len(documents)}, chunks={count}, "
        f"dimensions={settings.embedding_dimensions}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
