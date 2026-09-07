import asyncio
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelProviderError


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    source: str
    content: str


@dataclass(frozen=True)
class SearchResult(KnowledgeChunk):
    score: float


def chunk_markdown_documents(
    directory: Path,
    *,
    chunk_size: int = 600,
    overlap: int = 80,
) -> list[KnowledgeChunk]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller")

    chunks: list[KnowledgeChunk] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        start = 0
        index = 0
        while start < len(text):
            content = text[start : start + chunk_size].strip()
            if content:
                digest = sha256(f"{path.name}:{index}:{content}".encode()).hexdigest()
                chunks.append(KnowledgeChunk(digest, path.name, content))
            if start + chunk_size >= len(text):
                break
            start += chunk_size - overlap
            index += 1
    return chunks


class KnowledgeBase:
    def __init__(
        self,
        settings: Settings,
        model: BailianModel,
        *,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._collection = settings.knowledge_collection
        self._dimensions = settings.embedding_dimensions
        self._top_k = settings.knowledge_top_k
        self._min_score = settings.knowledge_min_score
        self._data_type = None
        if client is None:
            from pymilvus import DataType, MilvusClient

            self._data_type = DataType
            client = MilvusClient(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")
        self._client = client

    async def ingest(self, chunks: list[KnowledgeChunk]) -> int:
        if not chunks:
            return 0
        vectors = await self._model.embed_texts([chunk.content for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ModelProviderError
        await asyncio.to_thread(self._ensure_collection)
        await asyncio.to_thread(
            self._client.upsert,
            collection_name=self._collection,
            data=[
                {
                    "chunk_id": chunk.chunk_id,
                    "source": chunk.source,
                    "content": chunk.content,
                    "embedding": vector,
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
        )
        return len(chunks)

    async def search(self, question: str) -> list[SearchResult]:
        exists = await asyncio.to_thread(
            self._client.has_collection,
            collection_name=self._collection,
        )
        if not exists:
            return []
        vector = (await self._model.embed_texts([question]))[0]
        response = await asyncio.to_thread(
            self._client.search,
            collection_name=self._collection,
            data=[vector],
            anns_field="embedding",
            limit=self._top_k,
            output_fields=["chunk_id", "source", "content"],
            search_params={"metric_type": "COSINE", "params": {}},
        )
        return [
            SearchResult(
                chunk_id=hit["entity"]["chunk_id"],
                source=hit["entity"]["source"],
                content=hit["entity"]["content"],
                score=float(hit["distance"]),
            )
            for hit in response[0]
            if float(hit["distance"]) >= self._min_score
        ]

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)

    def _ensure_collection(self) -> None:
        if self._client.has_collection(collection_name=self._collection):
            return
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        varchar = self._data_type.VARCHAR if self._data_type else "VARCHAR"
        float_vector = self._data_type.FLOAT_VECTOR if self._data_type else "FLOAT_VECTOR"
        schema.add_field(
            field_name="chunk_id",
            datatype=varchar,
            is_primary=True,
            max_length=64,
        )
        schema.add_field(field_name="source", datatype=varchar, max_length=256)
        schema.add_field(field_name="content", datatype=varchar, max_length=4096)
        schema.add_field(
            field_name="embedding",
            datatype=float_vector,
            dim=self._dimensions,
        )
        indexes = self._client.prepare_index_params()
        indexes.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        self._client.create_collection(
            collection_name=self._collection,
            schema=schema,
            index_params=indexes,
        )
