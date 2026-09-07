from pathlib import Path

import pytest
from pydantic import SecretStr

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    chunk_markdown_documents,
)


class FakeModel:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.inputs: list[list[str]] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return self.vectors


class FakeSchema:
    def __init__(self) -> None:
        self.fields: list[dict] = []

    def add_field(self, **field) -> None:
        self.fields.append(field)


class FakeIndexParams:
    def __init__(self) -> None:
        self.indexes: list[dict] = []

    def add_index(self, **index) -> None:
        self.indexes.append(index)


class FakeMilvus:
    def __init__(self, *, exists: bool = False, search_result=None) -> None:
        self.exists = exists
        self.search_result = search_result or [[]]
        self.schema = FakeSchema()
        self.index_params = FakeIndexParams()
        self.created: dict | None = None
        self.upserted: dict | None = None
        self.searched: dict | None = None
        self.closed = False

    def has_collection(self, *, collection_name: str) -> bool:
        return self.exists

    def create_schema(self, **kwargs):
        return self.schema

    def prepare_index_params(self):
        return self.index_params

    def create_collection(self, **kwargs) -> None:
        self.created = kwargs
        self.exists = True

    def upsert(self, **kwargs) -> None:
        self.upserted = kwargs

    def search(self, **kwargs):
        self.searched = kwargs
        return self.search_result

    def close(self) -> None:
        self.closed = True


def settings() -> Settings:
    return Settings(_env_file=None, postgres_password=SecretStr("test-password"))


def test_markdown_chunking_is_stable_and_keeps_source(tmp_path: Path) -> None:
    document = tmp_path / "refund-policy.md"
    document.write_text("退款政策ABCDEFGHIJKL", encoding="utf-8")

    first = chunk_markdown_documents(tmp_path, chunk_size=10, overlap=2)
    second = chunk_markdown_documents(tmp_path, chunk_size=10, overlap=2)

    assert first == second
    assert [chunk.source for chunk in first] == ["refund-policy.md"] * 2
    assert [chunk.content for chunk in first] == ["退款政策ABCDEF", "EFGHIJKL"]
    assert len({chunk.chunk_id for chunk in first}) == len(first)


@pytest.mark.asyncio
async def test_ingestion_creates_explicit_dense_collection_and_upserts_chunks() -> None:
    model = FakeModel([[0.1, 0.2], [0.3, 0.4]])
    milvus = FakeMilvus()
    knowledge = KnowledgeBase(settings(), model, client=milvus)
    chunks = [
        KnowledgeChunk("chunk-1", "refund-policy.md", "七天内可申请退货。"),
        KnowledgeChunk("chunk-2", "shipping-policy.md", "配送延迟请联系客服。"),
    ]

    count = await knowledge.ingest(chunks)

    assert count == 2
    assert model.inputs == [["七天内可申请退货。", "配送延迟请联系客服。"]]
    assert milvus.created["collection_name"] == "ecommerce_knowledge"
    assert [field["field_name"] for field in milvus.schema.fields] == [
        "chunk_id",
        "source",
        "content",
        "embedding",
    ]
    assert milvus.index_params.indexes == [
        {
            "field_name": "embedding",
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
        }
    ]
    assert milvus.upserted == {
        "collection_name": "ecommerce_knowledge",
        "data": [
            {
                "chunk_id": "chunk-1",
                "source": "refund-policy.md",
                "content": "七天内可申请退货。",
                "embedding": [0.1, 0.2],
            },
            {
                "chunk_id": "chunk-2",
                "source": "shipping-policy.md",
                "content": "配送延迟请联系客服。",
                "embedding": [0.3, 0.4],
            },
        ],
    }


@pytest.mark.asyncio
async def test_dense_search_returns_only_top_k_hits_above_threshold() -> None:
    model = FakeModel([[0.9, 0.8]])
    milvus = FakeMilvus(
        exists=True,
        search_result=[
            [
                {
                    "distance": 0.82,
                    "entity": {
                        "chunk_id": "chunk-1",
                        "source": "refund-policy.md",
                        "content": "退款时效为七天。",
                    },
                },
                {
                    "distance": 0.4,
                    "entity": {
                        "chunk_id": "chunk-2",
                        "source": "payment-policy.md",
                        "content": "支持在线支付。",
                    },
                },
            ]
        ],
    )
    knowledge = KnowledgeBase(settings(), model, client=milvus)

    results = await knowledge.search("退款政策是什么？")

    assert [result.chunk_id for result in results] == ["chunk-1"]
    assert results[0].source == "refund-policy.md"
    assert results[0].score == 0.82
    assert milvus.searched == {
        "collection_name": "ecommerce_knowledge",
        "data": [[0.9, 0.8]],
        "anns_field": "embedding",
        "limit": 3,
        "output_fields": ["chunk_id", "source", "content"],
        "search_params": {"metric_type": "COSINE", "params": {}},
    }


@pytest.mark.asyncio
async def test_missing_collection_returns_no_knowledge_without_embedding_call() -> None:
    model = FakeModel([[0.1]])
    knowledge = KnowledgeBase(settings(), model, client=FakeMilvus())

    assert await knowledge.search("不存在的问题") == []
    assert model.inputs == []
