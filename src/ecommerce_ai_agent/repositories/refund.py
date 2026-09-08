from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ecommerce_ai_agent.models import HumanReview, Order, Refund
from ecommerce_ai_agent.models.enums import RefundStatus, ReviewStatus


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

    async def get_by_request_key(self, request_key: str) -> Refund | None:
        statement = (
            select(Refund)
            .where(Refund.request_key == request_key)
            .options(selectinload(Refund.human_review))
        )
        return await self._session.scalar(statement)

    async def count_recent_for_user(self, user_id: UUID, since: datetime) -> int:
        statement = (
            select(func.count())
            .select_from(Refund)
            .join(Order, Refund.order_id == Order.id)
            .where(
                Order.user_id == user_id,
                Refund.requested_at >= since,
                Refund.status.notin_([RefundStatus.REJECTED, RefundStatus.CANCELLED]),
            )
        )
        return int(await self._session.scalar(statement) or 0)

    def add_refund(self, refund: Refund) -> None:
        self._session.add(refund)

    def add_review(self, review: HumanReview) -> None:
        self._session.add(review)

    async def flush(self) -> None:
        await self._session.flush()

    async def get_review(self, review_id: UUID, *, for_update: bool = False) -> HumanReview | None:
        statement = (
            select(HumanReview)
            .where(HumanReview.id == review_id)
            .options(selectinload(HumanReview.refund))
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def list_pending_reviews(self) -> list[HumanReview]:
        statement = (
            select(HumanReview)
            .where(HumanReview.status == ReviewStatus.PENDING)
            .order_by(HumanReview.created_at)
            .options(selectinload(HumanReview.refund))
        )
        result = await self._session.scalars(statement)
        return list(result.all())
