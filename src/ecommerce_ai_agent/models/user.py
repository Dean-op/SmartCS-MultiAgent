from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ecommerce_ai_agent.models.base import Base, TimestampMixin
from ecommerce_ai_agent.models.enums import UserRole
from ecommerce_ai_agent.models.types import database_enum

if TYPE_CHECKING:
    from ecommerce_ai_agent.models.order import Order
    from ecommerce_ai_agent.models.refund import HumanReview


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(btrim(email)) > 0", name="ck_users_email_not_blank"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        database_enum(UserRole, "user_role"),
        nullable=False,
        default=UserRole.CUSTOMER,
        server_default=UserRole.CUSTOMER.value,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    orders: Mapped[list[Order]] = relationship(back_populates="user", lazy="raise")
    reviews: Mapped[list[HumanReview]] = relationship(
        back_populates="reviewer",
        foreign_keys="HumanReview.reviewer_id",
        lazy="raise",
    )
