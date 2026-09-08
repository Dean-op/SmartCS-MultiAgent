from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from ecommerce_ai_agent.auth import decode_access_token
from ecommerce_ai_agent.models.enums import UserRole
from ecommerce_ai_agent.services.data_types import UserData
from ecommerce_ai_agent.services.user import UserService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> UserData:
    try:
        user_id = decode_access_token(token, request.app.state.settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from exc
    database = request.app.state.database
    async with database.session_factory() as session:
        user = await UserService(session).get_user(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


async def require_admin(
    user: Annotated[UserData, Depends(get_current_user)],
) -> UserData:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return user
