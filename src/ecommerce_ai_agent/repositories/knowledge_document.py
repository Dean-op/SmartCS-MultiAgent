from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.models import KnowledgeDocument


class KnowledgeDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, document_id: UUID) -> KnowledgeDocument | None:
        return await self._session.get(KnowledgeDocument, document_id)

    async def get_by_source(self, source: str) -> KnowledgeDocument | None:
        return await self._session.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.source == source)
        )

    async def list(self) -> list[KnowledgeDocument]:
        result = await self._session.scalars(
            select(KnowledgeDocument).order_by(KnowledgeDocument.updated_at.desc())
        )
        return list(result.all())

    def add(self, document: KnowledgeDocument) -> None:
        self._session.add(document)

    async def delete(self, document: KnowledgeDocument) -> None:
        await self._session.delete(document)

    async def flush(self) -> None:
        await self._session.flush()
