from typing import Annotated

from fastapi import APIRouter, Depends

from ecommerce_ai_agent.schemas.chat import ChatRequest, ChatResponse
from ecommerce_ai_agent.schemas.error import ErrorResponse
from ecommerce_ai_agent.services.chat import ChatService

router = APIRouter()
chat_service = ChatService()


def get_chat_service() -> ChatService:
    return chat_service


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a chat message",
    responses={
        400: {"model": ErrorResponse, "description": "Application input error"},
        422: {"model": ErrorResponse, "description": "Request validation error"},
        500: {"model": ErrorResponse, "description": "Unexpected application error"},
    },
)
async def chat(
    request: ChatRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    return await service.respond(request)
