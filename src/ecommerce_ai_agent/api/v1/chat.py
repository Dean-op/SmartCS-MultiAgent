from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ecommerce_ai_agent.api.dependencies import get_current_user
from ecommerce_ai_agent.llm.errors import ModelConfigurationError
from ecommerce_ai_agent.schemas.chat import ChatRequest, ChatResponse
from ecommerce_ai_agent.schemas.error import ErrorResponse
from ecommerce_ai_agent.services.chat import ChatService
from ecommerce_ai_agent.services.data_types import UserData

router = APIRouter()


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
    request: ChatRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
    current_user: Annotated[UserData, Depends(get_current_user)],
) -> ChatResponse:
    return await service.respond(request, current_user.id)
