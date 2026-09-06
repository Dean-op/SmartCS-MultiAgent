from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ecommerce_ai_agent.models.base import Base, TimestampMixin
from ecommerce_ai_agent.models.enums import ShipmentStatus
from ecommerce_ai_agent.models.types import database_enum

if TYPE_CHECKING:
    from ecommerce_ai_agent.models.order import Order


class Shipment(TimestampMixin, Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_shipments_order_id"),
        UniqueConstraint("carrier", "tracking_number", name="uq_shipments_carrier_tracking"),
        CheckConstraint("length(btrim(carrier)) > 0", name="ck_shipments_carrier_not_blank"),
        CheckConstraint(
            "length(btrim(tracking_number)) > 0",
            name="ck_shipments_tracking_number_not_blank",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    carrier: Mapped[str] = mapped_column(String(100), nullable=False)
    tracking_number: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ShipmentStatus] = mapped_column(
        database_enum(ShipmentStatus, "shipment_status"), nullable=False
    )
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="shipment", lazy="raise")
