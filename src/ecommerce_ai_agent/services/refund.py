from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.repositories.refund import RefundRepository
from ecommerce_ai_agent.services.data_types import RefundData


class RefundService:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = RefundRepository(session)

    async def get_refund_by_number(self, refund_number: str) -> RefundData | None:
        refund = await self._repository.get_by_number(refund_number)
        return RefundData.model_validate(refund) if refund is not None else None

    async def list_order_refunds(self, order_id: UUID) -> list[RefundData]:
        refunds = await self._repository.list_by_order(order_id)
        return [RefundData.model_validate(refund) for refund in refunds]
