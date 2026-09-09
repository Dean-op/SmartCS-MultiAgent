from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SourceName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+\.(?:md|pdf)$")]


class KnowledgeDocumentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    source: SourceName = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=100_000)


class KnowledgeDocumentSummary(BaseModel):
    id: UUID
    title: str
    source: str
    content_hash: str
    indexed_hash: str | None
    indexed_at: datetime | None
    is_indexed: bool
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentDetail(KnowledgeDocumentSummary):
    content: str


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=1000)


class KnowledgeSearchItem(BaseModel):
    chunk_id: str
    source: str
    content: str
    score: float


class KnowledgeSearchResponse(BaseModel):
    items: list[KnowledgeSearchItem]


class KnowledgeRebuildResponse(BaseModel):
    documents: int
    chunks: int
    collection: str
    duration_ms: float
