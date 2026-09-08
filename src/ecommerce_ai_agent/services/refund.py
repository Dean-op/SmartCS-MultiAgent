from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.models import HumanReview, Refund
from ecommerce_ai_agent.models.enums import (
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    ReviewPriority,
    ReviewStatus,
)
from ecommerce_ai_agent.repositories.order import OrderRepository
from ecommerce_ai_agent.repositories.refund import RefundRepository
from ecommerce_ai_agent.services.data_types import RefundData


@dataclass(frozen=True)
class RefundCommandResult:
    outcome: str
    code: str | None = None
    refund_number: str | None = None
    amount: Decimal | None = None
    review_id: UUID | None = None


@dataclass(frozen=True)
class PendingReviewResult:
    review_id: UUID
    refund_number: str
    amount: Decimal
    reason: str
    thread_id: str
    status: ReviewStatus
    created_at: datetime


@dataclass(frozen=True)
class ReviewCommandResult:
    outcome: str
    refund_number: str | None = None
    thread_id: str | None = None


class RefundService:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = RefundRepository(session)
        self._orders = OrderRepository(session)

    async def get_refund_by_number(self, refund_number: str) -> RefundData | None:
        refund = await self._repository.get_by_number(refund_number)
        return RefundData.model_validate(refund) if refund is not None else None

    async def list_order_refunds(self, order_id: UUID) -> list[RefundData]:
        refunds = await self._repository.list_by_order(order_id)
        return [RefundData.model_validate(refund) for refund in refunds]

    async def request_refund(
        self,
        *,
        user_id: UUID,
        order_number: str,
        amount: Decimal | None,
        reason: str,
        thread_id: str,
        now: datetime,
        window_days: int = 30,
        auto_max: Decimal = Decimal("100.00"),
        recent_days: int = 30,
        recent_limit: int = 2,
    ) -> RefundCommandResult:
        order = await self._orders.get_for_user_for_update(user_id, order_number)
        if order is None:
            return RefundCommandResult("rejected", "order_not_found")

        request_key = sha256(f"{thread_id}:{order.id}".encode()).hexdigest()
        existing = await self._repository.get_by_request_key(request_key)
        if existing is not None:
            return RefundCommandResult(
                "duplicate",
                refund_number=existing.refund_number,
                amount=existing.amount,
                review_id=existing.human_review.id if existing.human_review else None,
            )
        if order.status == OrderStatus.CANCELLED:
            return RefundCommandResult("rejected", "order_cancelled")
        if order.payment_status == PaymentStatus.UNPAID:
            return RefundCommandResult("rejected", "order_not_paid")
        if order.payment_status == PaymentStatus.REFUNDED:
            return RefundCommandResult("rejected", "fully_refunded")

        anchor = order.shipment.delivered_at if order.shipment else None
        anchor = anchor or order.paid_at
        if anchor is None:
            return RefundCommandResult("rejected", "order_not_paid")
        if now > anchor + timedelta(days=window_days):
            return RefundCommandResult("rejected", "refund_window_expired")

        occupied = sum(
            (
                refund.amount
                for refund in order.refunds
                if refund.status not in (RefundStatus.REJECTED, RefundStatus.CANCELLED)
            ),
            Decimal("0.00"),
        )
        remaining = order.total_amount - occupied
        if remaining <= 0:
            return RefundCommandResult("rejected", "fully_refunded")
        requested = amount if amount is not None else remaining
        if requested <= 0:
            return RefundCommandResult("rejected", "invalid_amount")
        if requested > remaining:
            return RefundCommandResult("rejected", "amount_exceeds_refundable")

        recent_count = await self._repository.count_recent_for_user(
            user_id, now - timedelta(days=recent_days)
        )
        manual = requested > auto_max or recent_count >= recent_limit
        refund = Refund(
            id=uuid4(),
            refund_number=f"RF{uuid4().hex[:20].upper()}",
            request_key=request_key,
            order_id=order.id,
            amount=requested,
            reason=reason.strip(),
            status=RefundStatus.PENDING_REVIEW if manual else RefundStatus.COMPLETED,
            requested_at=now,
            completed_at=None if manual else now,
        )
        self._repository.add_refund(refund)
        review = None
        if manual:
            review = HumanReview(
                id=uuid4(),
                refund=refund,
                thread_id=thread_id,
                priority=ReviewPriority.HIGH,
            )
            self._repository.add_review(review)
        await self._repository.flush()
        return RefundCommandResult(
            "pending_review" if manual else "auto_completed",
            refund_number=refund.refund_number,
            amount=refund.amount,
            review_id=review.id if review else None,
        )

    async def list_pending_reviews(self) -> list[PendingReviewResult]:
        reviews = await self._repository.list_pending_reviews()
        return [
            PendingReviewResult(
                review_id=review.id,
                refund_number=review.refund.refund_number,
                amount=review.refund.amount,
                reason=review.refund.reason,
                thread_id=review.thread_id or "",
                status=review.status,
                created_at=review.created_at,
            )
            for review in reviews
            if review.thread_id
        ]

    async def get_review(self, review_id: UUID) -> PendingReviewResult | None:
        review = await self._repository.get_review(review_id)
        if review is None or review.thread_id is None:
            return None
        return PendingReviewResult(
            review_id=review.id,
            refund_number=review.refund.refund_number,
            amount=review.refund.amount,
            reason=review.refund.reason,
            thread_id=review.thread_id,
            status=review.status,
            created_at=review.created_at,
        )

    async def resolve_review(
        self,
        review_id: UUID,
        *,
        approve: bool,
        reviewer_id: UUID,
        note: str | None,
        now: datetime,
    ) -> ReviewCommandResult:
        review = await self._repository.get_review(review_id, for_update=True)
        if review is None:
            return ReviewCommandResult("not_found")
        if review.status != ReviewStatus.PENDING:
            return ReviewCommandResult(
                "already_processed", review.refund.refund_number, review.thread_id
            )
        review.status = ReviewStatus.APPROVED if approve else ReviewStatus.REJECTED
        review.reviewer_id = reviewer_id
        review.reviewer_note = note
        review.reviewed_at = now
        review.refund.status = RefundStatus.COMPLETED if approve else RefundStatus.REJECTED
        review.refund.completed_at = now if approve else None
        await self._repository.flush()
        return ReviewCommandResult(
            "approved" if approve else "rejected",
            review.refund.refund_number,
            review.thread_id,
        )
