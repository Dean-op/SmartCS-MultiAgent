from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ecommerce_ai_agent.models.base import Base, TimestampMixin
from ecommerce_ai_agent.models.enums import RefundStatus, ReviewPriority, ReviewStatus
from ecommerce_ai_agent.models.types import database_enum

if TYPE_CHECKING:
    from ecommerce_ai_agent.models.order import Order
    from ecommerce_ai_agent.models.user import User


class Refund(TimestampMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("refund_number", name="uq_refunds_refund_number"),
        CheckConstraint(
            "length(btrim(refund_number)) > 0",
            name="ck_refunds_refund_number_not_blank",
        ),
        CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
        CheckConstraint("length(btrim(reason)) > 0", name="ck_refunds_reason_not_blank"),
        Index("ix_refunds_order_created_at", "order_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    refund_number: Mapped[str] = mapped_column(String(32), nullable=False)
    order_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        database_enum(RefundStatus, "refund_status"), nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="refunds", lazy="raise")
    human_review: Mapped[HumanReview | None] = relationship(
        back_populates="refund",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )


class HumanReview(TimestampMixin, Base):
    __tablename__ = "human_reviews"
    __table_args__ = (UniqueConstraint("refund_id", name="uq_human_reviews_refund_id"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    refund_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("refunds.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    status: Mapped[ReviewStatus] = mapped_column(
        database_enum(ReviewStatus, "review_status"),
        nullable=False,
        default=ReviewStatus.PENDING,
        server_default=ReviewStatus.PENDING.value,
    )
    priority: Mapped[ReviewPriority] = mapped_column(
        database_enum(ReviewPriority, "review_priority"),
        nullable=False,
        default=ReviewPriority.NORMAL,
        server_default=ReviewPriority.NORMAL.value,
    )
    reviewer_note: Mapped[str | None] = mapped_column(String(1000))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    refund: Mapped[Refund] = relationship(back_populates="human_review", lazy="raise")
    reviewer: Mapped[User | None] = relationship(
        back_populates="reviews",
        foreign_keys=[reviewer_id],
        lazy="raise",
    )
