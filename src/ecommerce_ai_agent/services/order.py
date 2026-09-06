from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.repositories.order import OrderRepository
from ecommerce_ai_agent.services.data_types import OrderData


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = OrderRepository(session)

    async def get_order_by_number(self, order_number: str) -> OrderData | None:
        order = await self._repository.get_by_number(order_number)
        return OrderData.model_validate(order) if order is not None else None

    async def get_order_for_user(self, user_id: UUID, order_number: str) -> OrderData | None:
        order = await self._repository.get_for_user(user_id, order_number)
        return OrderData.model_validate(order) if order is not None else None

    async def list_user_orders(self, user_id: UUID) -> list[OrderData]:
        orders = await self._repository.list_by_user(user_id)
        return [OrderData.model_validate(order) for order in orders]
