from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ecommerce_ai_agent.models import Refund


class RefundRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_number(self, refund_number: str) -> Refund | None:
        statement = (
            select(Refund)
            .where(Refund.refund_number == refund_number.strip().upper())
            .options(selectinload(Refund.human_review))
        )
        return await self._session.scalar(statement)

    async def list_by_order(self, order_id: UUID) -> list[Refund]:
        statement = (
            select(Refund)
            .where(Refund.order_id == order_id)
            .order_by(Refund.created_at.desc())
            .options(selectinload(Refund.human_review))
        )
        result = await self._session.scalars(statement)
        return list(result.all())
