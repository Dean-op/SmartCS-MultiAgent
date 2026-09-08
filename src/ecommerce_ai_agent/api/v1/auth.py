from fastapi import APIRouter, HTTPException, Request, status

from ecommerce_ai_agent.auth import create_access_token
from ecommerce_ai_agent.schemas.auth import LoginRequest, TokenResponse
from ecommerce_ai_agent.services.user import UserService

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request) -> TokenResponse:
    async with request.app.state.database.session_factory() as session:
        user = await UserService(session).authenticate(payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        token = create_access_token(user.id, request.app.state.settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    return TokenResponse(
        access_token=token,
        expires_in=request.app.state.settings.jwt_access_token_expire_minutes * 60,
    )
