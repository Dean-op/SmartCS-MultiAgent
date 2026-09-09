import asyncio
import json
import logging
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ecommerce_ai_agent.api.dependencies import get_current_user
from ecommerce_ai_agent.api.errors import ApplicationError
from ecommerce_ai_agent.llm.errors import ModelConfigurationError, ModelError
from ecommerce_ai_agent.models.enums import ConversationMessageStatus
from ecommerce_ai_agent.observability import current_request_trace, record_error
from ecommerce_ai_agent.schemas.chat import AssistantMessage, ChatRequest, ChatResponse
from ecommerce_ai_agent.schemas.error import ErrorResponse
from ecommerce_ai_agent.services.chat import ChatService
from ecommerce_ai_agent.services.conversation import ConversationService
from ecommerce_ai_agent.services.data_types import UserData

router = APIRouter()
logger = logging.getLogger(__name__)
SAFETY_REFUSAL = "抱歉，该内容未通过安全审核，无法展示或执行。"


async def _review_text(request: Request, text: str, *, output: bool = False) -> str:
    safety = getattr(request.app.state, "safety_service", None)
    if safety is None:
        return text
    result = await safety.review(text)
    if result.action == "block":
        if output:
            return SAFETY_REFUSAL
        raise ApplicationError(
            code="unsafe_content",
            message="The request was blocked by content safety policy",
            status_code=400,
        )
    return result.text


def _replayed_response(turn) -> ChatResponse:
    message = turn.assistant_message
    if message is None or message.status in {
        ConversationMessageStatus.PENDING,
        ConversationMessageStatus.FAILED,
        ConversationMessageStatus.CANCELLED,
    }:
        raise ApplicationError(
            code="chat_request_in_progress",
            message="The original chat request has no completed response",
            status_code=409,
        )
    return ChatResponse(
        conversation_id=turn.conversation_id,
        status=(
            "pending_review"
            if message.status == ConversationMessageStatus.PENDING_REVIEW
            else "completed"
        ),
        message=AssistantMessage(
            id=message.id,
            content=message.content,
            created_at=message.created_at,
        ),
    )


def _sse(event: str, data: dict) -> str:
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def _chunks(text: str, size: int = 64):
    for start in range(0, len(text), size):
        yield text[start : start + size]


async def _with_heartbeats(
    source: AsyncIterator[dict], seconds: float = 15.0
) -> AsyncIterator[dict | None]:
    iterator = source.__aiter__()
    pending = asyncio.create_task(anext(iterator))
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=seconds)
            if not done:
                yield None
                continue
            try:
                yield pending.result()
            except StopAsyncIteration:
                return
            pending = asyncio.create_task(anext(iterator))
    finally:
        if not pending.done():
            pending.cancel()


def get_chat_service(request: Request) -> ChatService:
    service = getattr(request.app.state, "chat_service", None)
    if service is None:
        raise ModelConfigurationError
    return service


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a chat message",
    responses={
        400: {"model": ErrorResponse, "description": "Application input error"},
        422: {"model": ErrorResponse, "description": "Request validation error"},
        502: {"model": ErrorResponse, "description": "Model provider error"},
        503: {"model": ErrorResponse, "description": "Model provider unavailable"},
        504: {"model": ErrorResponse, "description": "Model provider timeout"},
        500: {"model": ErrorResponse, "description": "Unexpected application error"},
    },
)
async def chat(
    payload: ChatRequest,
    request: Request,
    service: Annotated[ChatService, Depends(get_chat_service)],
    current_user: Annotated[UserData, Depends(get_current_user)],
) -> ChatResponse:
    payload = payload.model_copy(update={"message": await _review_text(request, payload.message)})
    database = request.app.state.database
    if database is None:
        return await service.respond(payload, current_user.id)
    conversation_id = payload.conversation_id or uuid4()
    async with database.session_factory.begin() as session:
        turn = await ConversationService(session).start_turn(
            current_user.id,
            conversation_id,
            payload.message,
            client_message_id=payload.client_message_id,
        )
    if turn is None:
        raise ApplicationError(
            code="conversation_not_found",
            message="Conversation not found",
            status_code=404,
        )
    conversation_id = turn.conversation_id
    if turn.replayed:
        replayed = _replayed_response(turn)
        replayed.message.content = await _review_text(
            request, replayed.message.content, output=True
        )
        return replayed
    started = perf_counter()
    try:
        response = await service.respond(
            payload.model_copy(update={"conversation_id": conversation_id}), current_user.id
        )
    except Exception:
        async with database.session_factory.begin() as session:
            await ConversationService(session).complete_assistant(
                turn.assistant_message_id,
                content="",
                reasoning_content=None,
                status=ConversationMessageStatus.FAILED,
            )
        raise
    response.message.content = await _review_text(request, response.message.content, output=True)
    request_id, trace_id = current_request_trace()
    message_status = (
        ConversationMessageStatus.PENDING_REVIEW
        if response.status == "pending_review"
        else ConversationMessageStatus.COMPLETED
    )
    async with database.session_factory.begin() as session:
        await ConversationService(session).complete_assistant(
            turn.assistant_message_id,
            content=response.message.content,
            reasoning_content=None,
            status=message_status,
            request_id=request_id,
            trace_id=trace_id,
            latency_ms=round((perf_counter() - started) * 1000, 2),
        )
    response.message.id = turn.assistant_message_id
    return response


@router.post("/chat/stream", summary="Stream a chat response with SSE")
async def stream_chat(
    payload: ChatRequest,
    request: Request,
    service: Annotated[ChatService, Depends(get_chat_service)],
    current_user: Annotated[UserData, Depends(get_current_user)],
) -> StreamingResponse:
    payload = payload.model_copy(update={"message": await _review_text(request, payload.message)})
    database = request.app.state.database
    if database is None:
        raise ModelConfigurationError
    conversation_id = payload.conversation_id or uuid4()
    async with database.session_factory.begin() as session:
        turn = await ConversationService(session).start_turn(
            current_user.id,
            conversation_id,
            payload.message,
            client_message_id=payload.client_message_id,
        )
    if turn is None:
        raise ApplicationError(
            code="conversation_not_found",
            message="Conversation not found",
            status_code=404,
        )
    conversation_id = turn.conversation_id
    replayed = _replayed_response(turn) if turn.replayed else None
    request_id, trace_id = current_request_trace()
    started = perf_counter()
    stream_request = payload.model_copy(update={"conversation_id": conversation_id})

    async def persist(
        content: str,
        reasoning_content: str | None,
        message_status: ConversationMessageStatus,
        latency_ms: float | None = None,
    ) -> None:
        async with database.session_factory.begin() as session:
            await ConversationService(session).complete_assistant(
                turn.assistant_message_id,
                content=content,
                reasoning_content=reasoning_content,
                status=message_status,
                request_id=request_id,
                trace_id=trace_id,
                latency_ms=latency_ms,
            )

    async def event_stream() -> AsyncIterator[str]:
        partial_content = ""
        partial_reasoning = ""
        yield _sse(
            "conversation",
            {
                "conversation_id": str(conversation_id),
                "user_message_id": str(turn.user_message_id),
                "assistant_message_id": str(turn.assistant_message_id),
            },
        )
        if replayed is not None:
            stored = turn.assistant_message
            safe_reasoning = (
                await _review_text(request, stored.reasoning_content, output=True)
                if stored and stored.reasoning_content
                else ""
            )
            safe_content = await _review_text(request, replayed.message.content, output=True)
            if safe_reasoning:
                yield _sse("reasoning_delta", {"content": safe_reasoning})
            yield _sse("delta", {"content": safe_content})
            await persist(
                safe_content,
                safe_reasoning or None,
                stored.status if stored else ConversationMessageStatus.COMPLETED,
                stored.latency_ms if stored else None,
            )
            yield _sse(
                "done",
                {
                    "conversation_id": str(conversation_id),
                    "assistant_message_id": str(turn.assistant_message_id),
                    "status": replayed.status,
                    "reasoning_content": safe_reasoning,
                    "content": safe_content,
                    "latency_ms": stored.latency_ms if stored else None,
                    "created_at": replayed.message.created_at.isoformat(),
                    "replayed": True,
                },
            )
            return
        try:
            async for event in _with_heartbeats(
                service.stream_events(stream_request, current_user.id)
            ):
                if event is None:
                    yield ": ping\n\n"
                    continue
                if event["event"] == "conversation":
                    continue
                if event["event"] == "reasoning_delta":
                    partial_reasoning += str(event.get("content", ""))
                    continue
                elif event["event"] == "delta":
                    partial_content += str(event.get("content", ""))
                    continue
                if event["event"] == "done":
                    partial_content = event["content"]
                    partial_reasoning = event.get("reasoning_content") or ""
                    yield _sse("status", {"phase": "safety", "name": "output_review"})
                    safe_reasoning = (
                        await _review_text(request, partial_reasoning, output=True)
                        if partial_reasoning
                        else ""
                    )
                    safe_content = await _review_text(request, partial_content, output=True)
                    partial_reasoning = safe_reasoning
                    partial_content = safe_content
                    event["reasoning_content"] = safe_reasoning
                    event["content"] = safe_content
                    event["latency_ms"] = round((perf_counter() - started) * 1000, 2)
                    message_status = (
                        ConversationMessageStatus.PENDING_REVIEW
                        if event["status"] == "pending_review"
                        else ConversationMessageStatus.COMPLETED
                    )
                    await persist(
                        event["content"],
                        event.get("reasoning_content"),
                        message_status,
                        event["latency_ms"],
                    )
                    event["assistant_message_id"] = str(turn.assistant_message_id)
                    for chunk in _chunks(safe_reasoning):
                        yield _sse("reasoning_delta", {"content": chunk})
                    for chunk in _chunks(safe_content):
                        yield _sse("delta", {"content": chunk})
                yield _sse(
                    event["event"], {key: value for key, value in event.items() if key != "event"}
                )
        except asyncio.CancelledError:
            safe_reasoning = (
                await _review_text(request, partial_reasoning, output=True)
                if partial_reasoning
                else ""
            )
            safe_content = (
                await _review_text(request, partial_content, output=True) if partial_content else ""
            )
            await persist(
                safe_content,
                safe_reasoning or None,
                ConversationMessageStatus.CANCELLED,
                round((perf_counter() - started) * 1000, 2),
            )
            raise
        except ModelError as exc:
            record_error(type(exc).__name__)
            logger.warning("SSE chat failed", extra={"error_type": type(exc).__name__})
            safe_reasoning = (
                await _review_text(request, partial_reasoning, output=True)
                if partial_reasoning
                else ""
            )
            safe_content = (
                await _review_text(request, partial_content, output=True) if partial_content else ""
            )
            await persist(
                safe_content,
                safe_reasoning or None,
                ConversationMessageStatus.FAILED,
                round((perf_counter() - started) * 1000, 2),
            )
            yield _sse(
                "error",
                {
                    "code": exc.code,
                    "message": exc.public_message,
                    "retryable": exc.status_code >= 500,
                },
            )
        except Exception as exc:
            record_error(type(exc).__name__)
            logger.exception("SSE chat failed", extra={"error_type": type(exc).__name__})
            safe_reasoning = (
                await _review_text(request, partial_reasoning, output=True)
                if partial_reasoning
                else ""
            )
            safe_content = (
                await _review_text(request, partial_content, output=True) if partial_content else ""
            )
            await persist(
                safe_content,
                safe_reasoning or None,
                ConversationMessageStatus.FAILED,
                round((perf_counter() - started) * 1000, 2),
            )
            yield _sse(
                "error",
                {
                    "code": "internal_server_error",
                    "message": "An unexpected error occurred",
                    "retryable": False,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
