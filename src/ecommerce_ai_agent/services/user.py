from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.repositories.user import UserRepository
from ecommerce_ai_agent.services.data_types import UserData


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = UserRepository(session)

    async def get_user(self, user_id: UUID) -> UserData | None:
        user = await self._repository.get_by_id(user_id)
        return UserData.model_validate(user) if user is not None else None

    async def get_user_by_email(self, email: str) -> UserData | None:
        user = await self._repository.get_by_email(email)
        return UserData.model_validate(user) if user is not None else None
