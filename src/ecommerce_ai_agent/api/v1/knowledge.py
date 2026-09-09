import asyncio
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError

from ecommerce_ai_agent.api.dependencies import require_admin
from ecommerce_ai_agent.api.errors import ApplicationError
from ecommerce_ai_agent.knowledge import KnowledgeBase, chunk_markdown_text
from ecommerce_ai_agent.pdf_ingestion import PdfIngestionError, extract_pdf_markdown
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


async def _safe_content(request: Request, content: str) -> str:
    safety = getattr(request.app.state, "safety_service", None)
    if safety is None:
        return content
    result = await safety.review(content)
    if result.action == "block":
        raise ApplicationError(
            code="unsafe_knowledge_content",
            message="Knowledge content was blocked by safety policy",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return result.text


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
    safe_content = await _safe_content(request, payload.content)
    try:
        async with request.app.state.database.session_factory.begin() as session:
            document = await KnowledgeDocumentService(session).create(
                payload.title, payload.source, safe_content
            )
    except IntegrityError as exc:
        raise ApplicationError(
            code="knowledge_source_exists",
            message="Knowledge source already exists",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    return _detail(document)


@router.post(
    "/documents/pdf",
    response_model=KnowledgeDocumentDetail,
    status_code=status.HTTP_201_CREATED,
)
async def upload_pdf(
    request: Request,
    _admin: Annotated[UserData, Depends(require_admin)],
    file: Annotated[UploadFile, File()],
) -> KnowledgeDocumentDetail:
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf") or file.content_type not in {
        "application/pdf",
        "application/octet-stream",
    }:
        raise ApplicationError(
            code="pdf_invalid",
            message="Only PDF files are supported",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    settings = request.app.state.settings
    content = await file.read(settings.pdf_max_bytes + 1)
    try:
        extracted = await asyncio.to_thread(
            extract_pdf_markdown,
            content,
            filename,
            max_bytes=settings.pdf_max_bytes,
            max_pages=settings.pdf_max_pages,
            max_characters=settings.pdf_max_characters,
        )
    except PdfIngestionError as exc:
        raise ApplicationError(
            code=exc.code,
            message="PDF could not be safely extracted",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
    safe_content = await _safe_content(request, extracted.content)
    try:
        async with request.app.state.database.session_factory.begin() as session:
            document = await KnowledgeDocumentService(session).create(
                extracted.title, extracted.source, safe_content
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
    safe_content = await _safe_content(request, payload.content)
    try:
        async with request.app.state.database.session_factory.begin() as session:
            document = await KnowledgeDocumentService(session).update(
                document_id, payload.title, payload.source, safe_content
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
        snapshot = {document.id: document.content_hash for document in documents}
        chunks = [
            chunk
            for document in documents
            for chunk in chunk_markdown_text(document.source, document.content)
        ]
        count = await knowledge.ingest(chunks, rebuild=True)
        async with request.app.state.database.session_factory.begin() as session:
            await KnowledgeDocumentService(session).mark_indexed(snapshot)
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
