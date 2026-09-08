from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ecommerce_ai_agent.models import Order, OrderItem, Refund

ORDER_LOAD_OPTIONS = (
    selectinload(Order.items).selectinload(OrderItem.product),
    selectinload(Order.shipment),
    selectinload(Order.refunds).selectinload(Refund.human_review),
)


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_number(self, order_number: str) -> Order | None:
        statement = (
            select(Order)
            .where(Order.order_number == order_number.strip().upper())
            .options(*ORDER_LOAD_OPTIONS)
        )
        return await self._session.scalar(statement)

    async def get_for_user(self, user_id: UUID, order_number: str) -> Order | None:
        statement = (
            select(Order)
            .where(
                Order.user_id == user_id,
                Order.order_number == order_number.strip().upper(),
            )
            .options(*ORDER_LOAD_OPTIONS)
        )
        return await self._session.scalar(statement)

    async def get_for_user_for_update(self, user_id: UUID, order_number: str) -> Order | None:
        statement = (
            select(Order)
            .where(
                Order.user_id == user_id,
                Order.order_number == order_number.strip().upper(),
            )
            .options(*ORDER_LOAD_OPTIONS)
            .with_for_update()
        )
        return await self._session.scalar(statement)

    async def list_by_user(self, user_id: UUID) -> list[Order]:
        statement = (
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .options(*ORDER_LOAD_OPTIONS)
        )
        result = await self._session.scalars(statement)
        return list(result.all())
