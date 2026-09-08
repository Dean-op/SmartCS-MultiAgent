import asyncio
import re
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
        chunks.extend(chunk_markdown_text(path.name, text, chunk_size=chunk_size, overlap=overlap))
    return chunks


def chunk_markdown_text(
    source: str,
    text: str,
    *,
    chunk_size: int = 600,
    overlap: int = 80,
) -> list[KnowledgeChunk]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller")
    sections = re.split(r"(?m)(?=^## )", text.strip())
    if len(sections) > 1:
        title = sections[0].strip()
        sections = [f"{title}\n\n{section.strip()}" for section in sections[1:]]
    chunks: list[KnowledgeChunk] = []
    index = 0
    for section in sections:
        start = 0
        while start < len(section):
            content = section[start : start + chunk_size].strip()
            if content:
                digest = sha256(f"{source}:{index}:{content}".encode()).hexdigest()
                chunks.append(KnowledgeChunk(digest, source, content))
                index += 1
            if start + chunk_size >= len(section):
                break
            start += chunk_size - overlap
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
        self._candidate_k = settings.hybrid_candidate_k
        self._rrf_k = settings.rrf_k
        self._rerank_min_score = settings.rerank_min_score
        self._data_type = None
        self._function = None
        self._function_type = None
        self._ann_search_request = None
        self._rrf_ranker = None
        if client is None:
            from pymilvus import (
                AnnSearchRequest,
                DataType,
                Function,
                FunctionType,
                MilvusClient,
                RRFRanker,
            )

            self._data_type = DataType
            self._function = Function
            self._function_type = FunctionType
            self._ann_search_request = AnnSearchRequest
            self._rrf_ranker = RRFRanker
            client = MilvusClient(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")
        self._client = client

    async def ingest(self, chunks: list[KnowledgeChunk], *, rebuild: bool = False) -> int:
        if not chunks:
            if rebuild:
                await asyncio.to_thread(self._ensure_collection, True)
            return 0
        vectors = await self._model.embed_texts([chunk.content for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ModelProviderError
        await asyncio.to_thread(self._ensure_collection, rebuild)
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

    async def dense_search(self, question: str, *, limit: int | None = None) -> list[SearchResult]:
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
            limit=limit or self._top_k,
            output_fields=["chunk_id", "source", "content"],
            search_params={"metric_type": "COSINE", "params": {}},
        )
        return self._results(response)

    async def bm25_search(self, question: str, *, limit: int | None = None) -> list[SearchResult]:
        exists = await asyncio.to_thread(
            self._client.has_collection,
            collection_name=self._collection,
        )
        if not exists:
            return []
        response = await asyncio.to_thread(
            self._client.search,
            collection_name=self._collection,
            data=[question],
            anns_field="sparse_embedding",
            limit=limit or self._top_k,
            output_fields=["chunk_id", "source", "content"],
            search_params={"metric_type": "BM25", "params": {}},
        )
        return self._results(response)

    async def hybrid_search(self, question: str, *, limit: int | None = None) -> list[SearchResult]:
        exists = await asyncio.to_thread(
            self._client.has_collection,
            collection_name=self._collection,
        )
        if not exists:
            return []
        candidate_k = limit or self._candidate_k
        vector = (await self._model.embed_texts([question]))[0]
        dense = {
            "data": [vector],
            "anns_field": "embedding",
            "param": {"metric_type": "COSINE", "params": {}},
            "limit": candidate_k,
        }
        sparse = {
            "data": [question],
            "anns_field": "sparse_embedding",
            "param": {"metric_type": "BM25", "params": {}},
            "limit": candidate_k,
        }
        requests = [dense, sparse]
        ranker: Any = {"type": "rrf", "k": self._rrf_k}
        if self._ann_search_request and self._rrf_ranker:
            requests = [self._ann_search_request(**request) for request in requests]
            ranker = self._rrf_ranker(self._rrf_k)
        response = await asyncio.to_thread(
            self._client.hybrid_search,
            collection_name=self._collection,
            reqs=requests,
            ranker=ranker,
            limit=candidate_k,
            output_fields=["chunk_id", "source", "content"],
        )
        return self._results(response)

    async def search(self, question: str) -> list[SearchResult]:
        candidates = await self.hybrid_search(question)
        return await self.rerank_candidates(question, candidates)

    async def rerank_candidates(
        self, question: str, candidates: list[SearchResult]
    ) -> list[SearchResult]:
        rankings = await self._model.rerank_texts(
            question,
            [candidate.content for candidate in candidates],
            top_n=self._top_k,
        )
        return [
            SearchResult(
                chunk_id=candidates[item.index].chunk_id,
                source=candidates[item.index].source,
                content=candidates[item.index].content,
                score=item.score,
            )
            for item in rankings
            if item.score >= self._rerank_min_score
        ]

    @staticmethod
    def _results(response: Any) -> list[SearchResult]:
        return [
            SearchResult(
                chunk_id=hit["entity"]["chunk_id"],
                source=hit["entity"]["source"],
                content=hit["entity"]["content"],
                score=float(hit["distance"]),
            )
            for hit in response[0]
        ]

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)

    def _ensure_collection(self, rebuild: bool) -> None:
        exists = self._client.has_collection(collection_name=self._collection)
        if exists and not rebuild:
            return
        if exists:
            self._client.drop_collection(collection_name=self._collection)
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        varchar = self._data_type.VARCHAR if self._data_type else "VARCHAR"
        float_vector = self._data_type.FLOAT_VECTOR if self._data_type else "FLOAT_VECTOR"
        sparse_vector = (
            self._data_type.SPARSE_FLOAT_VECTOR if self._data_type else "SPARSE_FLOAT_VECTOR"
        )
        schema.add_field(
            field_name="chunk_id",
            datatype=varchar,
            is_primary=True,
            max_length=64,
        )
        schema.add_field(field_name="source", datatype=varchar, max_length=256)
        schema.add_field(
            field_name="content",
            datatype=varchar,
            max_length=4096,
            enable_analyzer=True,
            analyzer_params={"type": "chinese"},
        )
        schema.add_field(
            field_name="embedding",
            datatype=float_vector,
            dim=self._dimensions,
        )
        schema.add_field(field_name="sparse_embedding", datatype=sparse_vector)
        function: Any = {
            "name": "content_bm25",
            "input_field_names": ["content"],
            "output_field_names": ["sparse_embedding"],
            "function_type": "BM25",
        }
        if self._function and self._function_type:
            function = self._function(
                name="content_bm25",
                input_field_names=["content"],
                output_field_names=["sparse_embedding"],
                function_type=self._function_type.BM25,
            )
        schema.add_function(function)
        indexes = self._client.prepare_index_params()
        indexes.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        indexes.add_index(
            field_name="sparse_embedding",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
        )
        self._client.create_collection(
            collection_name=self._collection,
            schema=schema,
            index_params=indexes,
        )
