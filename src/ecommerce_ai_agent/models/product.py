from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ecommerce_ai_agent.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from ecommerce_ai_agent.models.order import OrderItem


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_products_sku"),
        CheckConstraint("length(btrim(sku)) > 0", name="ck_products_sku_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_products_name_not_blank"),
        CheckConstraint("unit_price >= 0", name="ck_products_unit_price_non_negative"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    order_items: Mapped[list[OrderItem]] = relationship(back_populates="product", lazy="raise")
