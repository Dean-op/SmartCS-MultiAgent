from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from ecommerce_ai_agent.api.dependencies import require_admin
from ecommerce_ai_agent.api.errors import ApplicationError
from ecommerce_ai_agent.api.v1.chat import get_chat_service
from ecommerce_ai_agent.models.enums import ReviewStatus
from ecommerce_ai_agent.schemas.chat import ChatResponse
from ecommerce_ai_agent.schemas.review import PendingReviewResponse, ReviewActionRequest
from ecommerce_ai_agent.services.chat import ChatService
from ecommerce_ai_agent.services.conversation import ConversationService
from ecommerce_ai_agent.services.data_types import UserData
from ecommerce_ai_agent.services.refund import RefundService

router = APIRouter(prefix="/reviews")


@router.get("/pending", response_model=list[PendingReviewResponse])
async def list_pending_reviews(
    request: Request,
    _admin: Annotated[UserData, Depends(require_admin)],
) -> list[PendingReviewResponse]:
    async with request.app.state.database.session_factory() as session:
        reviews = await RefundService(session).list_pending_reviews()
    return [
        PendingReviewResponse.model_validate(review, from_attributes=True) for review in reviews
    ]


async def _resolve_review(
    review_id: UUID,
    decision: Literal["approve", "reject"],
    payload: ReviewActionRequest,
    request: Request,
    admin: UserData,
    chat_service: ChatService,
) -> ChatResponse:
    async with request.app.state.database.session_factory() as session:
        review = await RefundService(session).get_review(review_id)
    if review is None:
        raise ApplicationError(
            code="review_not_found",
            message="Review not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if review.status != ReviewStatus.PENDING:
        raise ApplicationError(
            code="review_already_processed",
            message="Review has already been processed",
            status_code=status.HTTP_409_CONFLICT,
        )
    try:
        conversation_id = UUID(review.thread_id.rsplit(":", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ApplicationError(
            code="review_thread_invalid",
            message="Review workflow cannot be resumed",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    response = await chat_service.resume_review(
        review.thread_id,
        conversation_id,
        decision,
        admin.id,
        payload.note,
    )
    async with request.app.state.database.session_factory.begin() as session:
        await ConversationService(session).resolve_pending_review(
            conversation_id, response.message.content
        )
    return response


@router.post("/{review_id}/approve", response_model=ChatResponse)
async def approve_review(
    review_id: UUID,
    payload: ReviewActionRequest,
    request: Request,
    admin: Annotated[UserData, Depends(require_admin)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    return await _resolve_review(review_id, "approve", payload, request, admin, chat_service)


@router.post("/{review_id}/reject", response_model=ChatResponse)
async def reject_review(
    review_id: UUID,
    payload: ReviewActionRequest,
    request: Request,
    admin: Annotated[UserData, Depends(require_admin)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    return await _resolve_review(review_id, "reject", payload, request, admin, chat_service)
