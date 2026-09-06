from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ecommerce_ai_agent.models.enums import (
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    ReviewPriority,
    ReviewStatus,
    ShipmentStatus,
    UserRole,
)


class ServiceData(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)


class UserData(ServiceData):
    id: UUID
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductData(ServiceData):
    id: UUID
    sku: str
    name: str
    description: str | None
    unit_price: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrderItemData(ServiceData):
    id: UUID
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    product: ProductData


class ShipmentData(ServiceData):
    id: UUID
    carrier: str
    tracking_number: str
    status: ShipmentStatus
    shipped_at: datetime | None
    estimated_delivery_at: datetime | None
    delivered_at: datetime | None


class HumanReviewData(ServiceData):
    id: UUID
    reviewer_id: UUID | None
    status: ReviewStatus
    priority: ReviewPriority
    reviewer_note: str | None
    reviewed_at: datetime | None


class RefundData(ServiceData):
    id: UUID
    refund_number: str
    order_id: UUID
    amount: Decimal
    reason: str
    status: RefundStatus
    requested_at: datetime
    completed_at: datetime | None
    human_review: HumanReviewData | None


class OrderData(ServiceData):
    id: UUID
    order_number: str
    user_id: UUID
    status: OrderStatus
    payment_status: PaymentStatus
    total_amount: Decimal
    paid_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: tuple[OrderItemData, ...]
    shipment: ShipmentData | None
    refunds: tuple[RefundData, ...]
