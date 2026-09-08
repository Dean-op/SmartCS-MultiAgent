import asyncio
import json
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
from ecommerce_ai_agent.observability import current_request_trace
from ecommerce_ai_agent.schemas.chat import ChatRequest, ChatResponse
from ecommerce_ai_agent.schemas.error import ErrorResponse
from ecommerce_ai_agent.services.chat import ChatService
from ecommerce_ai_agent.services.conversation import ConversationService
from ecommerce_ai_agent.services.data_types import UserData

router = APIRouter()


def _sse(event: str, data: dict) -> str:
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


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
    database = request.app.state.database
    if database is None:
        return await service.respond(payload, current_user.id)
    conversation_id = payload.conversation_id or uuid4()
    async with database.session_factory.begin() as session:
        turn = await ConversationService(session).start_turn(
            current_user.id, conversation_id, payload.message
        )
    if turn is None:
        raise ApplicationError(
            code="conversation_not_found",
            message="Conversation not found",
            status_code=404,
        )
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
    database = request.app.state.database
    if database is None:
        raise ModelConfigurationError
    conversation_id = payload.conversation_id or uuid4()
    async with database.session_factory.begin() as session:
        turn = await ConversationService(session).start_turn(
            current_user.id, conversation_id, payload.message
        )
    if turn is None:
        raise ApplicationError(
            code="conversation_not_found",
            message="Conversation not found",
            status_code=404,
        )
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
        yield _sse(
            "conversation",
            {
                "conversation_id": str(conversation_id),
                "user_message_id": str(turn.user_message_id),
                "assistant_message_id": str(turn.assistant_message_id),
            },
        )
        try:
            async for event in _with_heartbeats(
                service.stream_events(stream_request, current_user.id)
            ):
                if event is None:
                    yield ": ping\n\n"
                    continue
                if event["event"] == "conversation":
                    continue
                if event["event"] == "done":
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
                yield _sse(
                    event["event"], {key: value for key, value in event.items() if key != "event"}
                )
        except asyncio.CancelledError:
            await persist("", None, ConversationMessageStatus.CANCELLED)
            raise
        except ModelError as exc:
            await persist("", None, ConversationMessageStatus.FAILED)
            yield _sse(
                "error",
                {
                    "code": exc.code,
                    "message": exc.public_message,
                    "retryable": exc.status_code >= 500,
                },
            )
        except Exception:
            await persist("", None, ConversationMessageStatus.FAILED)
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
