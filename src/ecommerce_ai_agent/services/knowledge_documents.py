from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.models import KnowledgeDocument
from ecommerce_ai_agent.repositories.knowledge_document import KnowledgeDocumentRepository
from ecommerce_ai_agent.services.data_types import KnowledgeDocumentData


def content_hash(content: str) -> str:
    return sha256(content.encode()).hexdigest()


class KnowledgeDocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = KnowledgeDocumentRepository(session)

    @staticmethod
    def _data(document: KnowledgeDocument) -> KnowledgeDocumentData:
        return KnowledgeDocumentData(
            **{
                key: getattr(document, key)
                for key in (
                    "id",
                    "title",
                    "source",
                    "content",
                    "content_hash",
                    "indexed_hash",
                    "indexed_at",
                    "created_at",
                    "updated_at",
                )
            },
            is_indexed=(
                document.indexed_hash is not None and document.indexed_hash == document.content_hash
            ),
        )

    async def list(self) -> list[KnowledgeDocumentData]:
        return [self._data(item) for item in await self._repository.list()]

    async def get(self, document_id: UUID) -> KnowledgeDocumentData | None:
        document = await self._repository.get(document_id)
        return self._data(document) if document else None

    async def create(self, title: str, source: str, content: str) -> KnowledgeDocumentData:
        document = KnowledgeDocument(
            title=title.strip(),
            source=source.strip().lower(),
            content=content.strip(),
            content_hash=content_hash(content.strip()),
        )
        self._repository.add(document)
        await self._repository.flush()
        return self._data(document)

    async def update(
        self, document_id: UUID, title: str, source: str, content: str
    ) -> KnowledgeDocumentData | None:
        document = await self._repository.get(document_id)
        if document is None:
            return None
        document.title = title.strip()
        document.source = source.strip().lower()
        document.content = content.strip()
        document.content_hash = content_hash(document.content)
        document.updated_at = datetime.now(UTC)
        await self._repository.flush()
        return self._data(document)

    async def delete(self, document_id: UUID) -> bool:
        document = await self._repository.get(document_id)
        if document is None:
            return False
        await self._repository.delete(document)
        await self._repository.flush()
        return True

    async def mark_all_indexed(self) -> None:
        indexed_at = datetime.now(UTC)
        for document in await self._repository.list():
            document.indexed_hash = document.content_hash
            document.indexed_at = indexed_at
        await self._repository.flush()
