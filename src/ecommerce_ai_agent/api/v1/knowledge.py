import asyncio
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.exc import IntegrityError

from ecommerce_ai_agent.api.dependencies import require_admin
from ecommerce_ai_agent.api.errors import ApplicationError
from ecommerce_ai_agent.knowledge import KnowledgeBase, chunk_markdown_text
from ecommerce_ai_agent.schemas.knowledge import (
    KnowledgeDocumentDetail,
    KnowledgeDocumentSummary,
    KnowledgeDocumentWrite,
    KnowledgeRebuildResponse,
    KnowledgeSearchItem,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from ecommerce_ai_agent.services.data_types import UserData
from ecommerce_ai_agent.services.knowledge_documents import KnowledgeDocumentService

router = APIRouter(prefix="/knowledge")


def _knowledge(request: Request) -> KnowledgeBase:
    knowledge = getattr(request.app.state, "knowledge_base", None)
    if knowledge is None:
        raise ApplicationError(
            code="knowledge_unavailable",
            message="Knowledge base is unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return knowledge


def _detail(document) -> KnowledgeDocumentDetail:
    return KnowledgeDocumentDetail.model_validate(document, from_attributes=True)


@router.get("/documents", response_model=list[KnowledgeDocumentSummary])
async def list_documents(
    request: Request,
    _admin: Annotated[UserData, Depends(require_admin)],
) -> list[KnowledgeDocumentSummary]:
    async with request.app.state.database.session_factory() as session:
        documents = await KnowledgeDocumentService(session).list()
    return [
        KnowledgeDocumentSummary.model_validate(item, from_attributes=True) for item in documents
    ]


@router.post(
    "/documents",
    response_model=KnowledgeDocumentDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    payload: KnowledgeDocumentWrite,
    request: Request,
    _admin: Annotated[UserData, Depends(require_admin)],
) -> KnowledgeDocumentDetail:
    try:
        async with request.app.state.database.session_factory.begin() as session:
            document = await KnowledgeDocumentService(session).create(
                payload.title, payload.source, payload.content
            )
    except IntegrityError as exc:
        raise ApplicationError(
            code="knowledge_source_exists",
            message="Knowledge source already exists",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    return _detail(document)


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentDetail)
async def get_document(
    document_id: UUID,
    request: Request,
    _admin: Annotated[UserData, Depends(require_admin)],
) -> KnowledgeDocumentDetail:
    async with request.app.state.database.session_factory() as session:
        document = await KnowledgeDocumentService(session).get(document_id)
    if document is None:
        raise ApplicationError(
            code="knowledge_document_not_found",
            message="Knowledge document not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return _detail(document)


@router.put("/documents/{document_id}", response_model=KnowledgeDocumentDetail)
async def update_document(
    document_id: UUID,
    payload: KnowledgeDocumentWrite,
    request: Request,
    _admin: Annotated[UserData, Depends(require_admin)],
) -> KnowledgeDocumentDetail:
    try:
        async with request.app.state.database.session_factory.begin() as session:
            document = await KnowledgeDocumentService(session).update(
                document_id, payload.title, payload.source, payload.content
            )
    except IntegrityError as exc:
        raise ApplicationError(
            code="knowledge_source_exists",
            message="Knowledge source already exists",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    if document is None:
        raise ApplicationError(
            code="knowledge_document_not_found",
            message="Knowledge document not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return _detail(document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    request: Request,
    _admin: Annotated[UserData, Depends(require_admin)],
) -> Response:
    async with request.app.state.database.session_factory.begin() as session:
        deleted = await KnowledgeDocumentService(session).delete(document_id)
    if not deleted:
        raise ApplicationError(
            code="knowledge_document_not_found",
            message="Knowledge document not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/rebuild", response_model=KnowledgeRebuildResponse)
async def rebuild_knowledge(
    request: Request,
    _admin: Annotated[UserData, Depends(require_admin)],
    knowledge: Annotated[KnowledgeBase, Depends(_knowledge)],
) -> KnowledgeRebuildResponse:
    lock: asyncio.Lock = request.app.state.knowledge_rebuild_lock
    if lock.locked():
        raise ApplicationError(
            code="knowledge_rebuild_in_progress",
            message="Knowledge rebuild is already in progress",
            status_code=status.HTTP_409_CONFLICT,
        )
    started = perf_counter()
    async with lock:
        async with request.app.state.database.session_factory() as session:
            documents = await KnowledgeDocumentService(session).list()
        chunks = [
            chunk
            for document in documents
            for chunk in chunk_markdown_text(document.source, document.content)
        ]
        count = await knowledge.ingest(chunks, rebuild=True)
        async with request.app.state.database.session_factory.begin() as session:
            await KnowledgeDocumentService(session).mark_all_indexed()
    return KnowledgeRebuildResponse(
        documents=len(documents),
        chunks=count,
        collection=request.app.state.settings.knowledge_collection,
        duration_ms=round((perf_counter() - started) * 1000, 2),
    )


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    payload: KnowledgeSearchRequest,
    _admin: Annotated[UserData, Depends(require_admin)],
    knowledge: Annotated[KnowledgeBase, Depends(_knowledge)],
) -> KnowledgeSearchResponse:
    results = await knowledge.search(payload.query)
    return KnowledgeSearchResponse(
        items=[KnowledgeSearchItem.model_validate(item, from_attributes=True) for item in results]
    )
