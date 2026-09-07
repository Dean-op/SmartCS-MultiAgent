from pathlib import Path

import pytest
from pydantic import SecretStr

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    chunk_markdown_documents,
)
from ecommerce_ai_agent.llm.client import RerankResult


class FakeModel:
    def __init__(
        self,
        vectors: list[list[float]],
        rerank_results: list[RerankResult] | None = None,
    ) -> None:
        self.vectors = vectors
        self.rerank_results = rerank_results or []
        self.inputs: list[list[str]] = []
        self.rerank_calls: list[tuple[str, list[str], int]] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return self.vectors

    async def rerank_texts(
        self, query: str, documents: list[str], *, top_n: int
    ) -> list[RerankResult]:
        self.rerank_calls.append((query, documents, top_n))
        return self.rerank_results


class FakeSchema:
    def __init__(self) -> None:
        self.fields: list[dict] = []
        self.functions: list[dict] = []

    def add_field(self, **field) -> None:
        self.fields.append(field)

    def add_function(self, function) -> None:
        self.functions.append(function)


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
        self.hybrid_searched: dict | None = None
        self.dropped: str | None = None
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

    def drop_collection(self, *, collection_name: str) -> None:
        self.dropped = collection_name
        self.exists = False

    def upsert(self, **kwargs) -> None:
        self.upserted = kwargs

    def search(self, **kwargs):
        self.searched = kwargs
        return self.search_result

    def hybrid_search(self, **kwargs):
        self.hybrid_searched = kwargs
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


def test_markdown_headings_create_separate_semantic_chunks(tmp_path: Path) -> None:
    document = tmp_path / "policy.md"
    document.write_text(
        "# 平台政策\n\n## 退款期限\n七天内申请。\n\n## 质量问题\n需要提交照片。",
        encoding="utf-8",
    )

    chunks = chunk_markdown_documents(tmp_path)

    assert [chunk.content for chunk in chunks] == [
        "# 平台政策\n\n## 退款期限\n七天内申请。",
        "# 平台政策\n\n## 质量问题\n需要提交照片。",
    ]


@pytest.mark.asyncio
async def test_ingestion_rebuilds_collection_with_dense_and_bm25_schema() -> None:
    model = FakeModel([[0.1, 0.2], [0.3, 0.4]])
    milvus = FakeMilvus(exists=True)
    knowledge = KnowledgeBase(settings(), model, client=milvus)
    chunks = [
        KnowledgeChunk("chunk-1", "refund-policy.md", "七天内可申请退货。"),
        KnowledgeChunk("chunk-2", "shipping-policy.md", "配送延迟请联系客服。"),
    ]

    count = await knowledge.ingest(chunks, rebuild=True)

    assert count == 2
    assert model.inputs == [["七天内可申请退货。", "配送延迟请联系客服。"]]
    assert milvus.dropped == "ecommerce_knowledge"
    assert milvus.created["collection_name"] == "ecommerce_knowledge"
    assert [field["field_name"] for field in milvus.schema.fields] == [
        "chunk_id",
        "source",
        "content",
        "embedding",
        "sparse_embedding",
    ]
    content_field = next(
        field for field in milvus.schema.fields if field["field_name"] == "content"
    )
    assert content_field["enable_analyzer"] is True
    assert content_field["analyzer_params"] == {"type": "chinese"}
    assert milvus.schema.functions == [
        {
            "name": "content_bm25",
            "input_field_names": ["content"],
            "output_field_names": ["sparse_embedding"],
            "function_type": "BM25",
        }
    ]
    assert milvus.index_params.indexes == [
        {
            "field_name": "embedding",
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
        },
        {
            "field_name": "sparse_embedding",
            "index_type": "SPARSE_INVERTED_INDEX",
            "metric_type": "BM25",
        },
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
async def test_dense_search_keeps_existing_cosine_path() -> None:
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

    results = await knowledge.dense_search("退款政策是什么？")

    assert [result.chunk_id for result in results] == ["chunk-1", "chunk-2"]
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
async def test_bm25_search_sends_raw_query_to_sparse_field() -> None:
    milvus = FakeMilvus(
        exists=True,
        search_result=[
            [
                {
                    "distance": 4.2,
                    "entity": {
                        "chunk_id": "chunk-bm25",
                        "source": "shipping-policy.md",
                        "content": "物流超过48小时没有更新。",
                    },
                }
            ]
        ],
    )
    knowledge = KnowledgeBase(settings(), FakeModel([]), client=milvus)

    results = await knowledge.bm25_search("物流48小时")

    assert [result.chunk_id for result in results] == ["chunk-bm25"]
    assert milvus.searched == {
        "collection_name": "ecommerce_knowledge",
        "data": ["物流48小时"],
        "anns_field": "sparse_embedding",
        "limit": 3,
        "output_fields": ["chunk_id", "source", "content"],
        "search_params": {"metric_type": "BM25", "params": {}},
    }


@pytest.mark.asyncio
async def test_hybrid_search_uses_dense_bm25_and_rrf() -> None:
    milvus = FakeMilvus(
        exists=True,
        search_result=[
            [
                {
                    "distance": 0.032,
                    "entity": {
                        "chunk_id": "hybrid-1",
                        "source": "refund-policy.md",
                        "content": "退款时效为七天。",
                    },
                }
            ]
        ],
    )
    config = settings().model_copy(update={"hybrid_candidate_k": 10, "rrf_k": 60.0})
    knowledge = KnowledgeBase(config, FakeModel([[0.7, 0.8]]), client=milvus)

    results = await knowledge.hybrid_search("七天退款")

    assert [result.chunk_id for result in results] == ["hybrid-1"]
    assert milvus.hybrid_searched == {
        "collection_name": "ecommerce_knowledge",
        "reqs": [
            {
                "data": [[0.7, 0.8]],
                "anns_field": "embedding",
                "param": {"metric_type": "COSINE", "params": {}},
                "limit": 10,
            },
            {
                "data": ["七天退款"],
                "anns_field": "sparse_embedding",
                "param": {"metric_type": "BM25", "params": {}},
                "limit": 10,
            },
        ],
        "ranker": {"type": "rrf", "k": 60.0},
        "limit": 10,
        "output_fields": ["chunk_id", "source", "content"],
    }


@pytest.mark.asyncio
async def test_default_search_reranks_hybrid_candidates_and_applies_threshold() -> None:
    milvus = FakeMilvus(
        exists=True,
        search_result=[
            [
                {
                    "distance": 0.03,
                    "entity": {
                        "chunk_id": "candidate-1",
                        "source": "payment-policy.md",
                        "content": "支付政策。",
                    },
                },
                {
                    "distance": 0.02,
                    "entity": {
                        "chunk_id": "candidate-2",
                        "source": "refund-policy.md",
                        "content": "七天退款政策。",
                    },
                },
            ]
        ],
    )
    model = FakeModel(
        [[0.7, 0.8]],
        [RerankResult(index=1, score=0.92), RerankResult(index=0, score=0.1)],
    )
    knowledge = KnowledgeBase(settings(), model, client=milvus)

    results = await knowledge.search("七天退款")

    assert [(result.chunk_id, result.score) for result in results] == [("candidate-2", 0.92)]
    assert model.rerank_calls == [("七天退款", ["支付政策。", "七天退款政策。"], 3)]


@pytest.mark.asyncio
async def test_missing_collection_returns_no_knowledge_without_embedding_call() -> None:
    model = FakeModel([[0.1]])
    knowledge = KnowledgeBase(settings(), model, client=FakeMilvus())

    assert await knowledge.search("不存在的问题") == []
    assert model.inputs == []
