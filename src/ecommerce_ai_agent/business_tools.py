import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.services.catalog import CatalogService
from ecommerce_ai_agent.services.order import OrderService
from ecommerce_ai_agent.services.refund import RefundService

logger = logging.getLogger(__name__)


class OrderArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    order_number: str = Field(min_length=1, max_length=32)


class ProductArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: str = Field(min_length=1, max_length=64)


class RefundArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    refund_number: str = Field(min_length=1, max_length=32)


class RefundRequestArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    order_number: str = Field(min_length=1, max_length=32)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(min_length=2, max_length=500)


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_current_user_order",
            "description": "按订单号查询当前登录用户自己的订单、商品项和物流状态。",
            "parameters": OrderArguments.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_by_sku",
            "description": "按 SKU 查询商品名称、价格和在售状态。",
            "parameters": ProductArguments.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_user_refund",
            "description": "按退款单号查询当前登录用户自己的退款进度。",
            "parameters": RefundArguments.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_refund",
            "description": "为当前登录用户的订单申请退款。金额可省略，由系统计算合法剩余金额。",
            "parameters": RefundRequestArguments.model_json_schema(),
        },
    },
]


class BusinessTools:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def run(self, name: str, arguments: str, user_id: UUID) -> str:
        try:
            async with self._session_factory() as session:
                match name:
                    case "get_current_user_order":
                        parsed = OrderArguments.model_validate_json(arguments)
                        result = await self._order(session, user_id, parsed.order_number)
                    case "get_product_by_sku":
                        parsed = ProductArguments.model_validate_json(arguments)
                        result = await self._product(session, parsed.sku)
                    case "get_current_user_refund":
                        parsed = RefundArguments.model_validate_json(arguments)
                        result = await self._refund(session, user_id, parsed.refund_number)
                    case _:
                        return self._json({"error": "unknown_tool"})
        except ValidationError:
            return self._json({"error": "invalid_arguments"})

        logger.info("Business tool executed", extra={"tool_name": name})
        return self._json(result)

    async def request_refund(self, arguments: str, user_id: UUID, thread_id: str) -> str:
        try:
            parsed = RefundRequestArguments.model_validate_json(arguments)
        except ValidationError:
            return self._json({"outcome": "rejected", "code": "invalid_arguments"})
        settings = self._settings
        async with self._session_factory.begin() as session:
            result = await RefundService(session).request_refund(
                user_id=user_id,
                order_number=parsed.order_number,
                amount=parsed.amount,
                reason=parsed.reason,
                thread_id=thread_id,
                now=datetime.now(UTC),
                window_days=settings.refund_window_days if settings else 30,
                auto_max=settings.refund_auto_approve_max_amount if settings else Decimal("100.00"),
                recent_days=settings.refund_recent_count_days if settings else 30,
                recent_limit=settings.refund_recent_count_limit if settings else 2,
            )
        return self._json(
            {
                "outcome": result.outcome,
                "code": result.code,
                "refund_number": result.refund_number,
                "amount": str(result.amount) if result.amount is not None else None,
                "review_id": str(result.review_id) if result.review_id else None,
                "thread_id": thread_id,
            }
        )

    async def resolve_refund_review(
        self,
        review_id: UUID,
        approve: bool,
        reviewer_id: UUID,
        note: str | None,
    ) -> str:
        async with self._session_factory.begin() as session:
            result = await RefundService(session).resolve_review(
                review_id,
                approve=approve,
                reviewer_id=reviewer_id,
                note=note,
                now=datetime.now(UTC),
            )
        return self._json({"outcome": result.outcome, "refund_number": result.refund_number})

    async def _order(
        self, session: AsyncSession, user_id: UUID, order_number: str
    ) -> dict[str, Any]:
        order = await OrderService(session).get_order_for_user(user_id, order_number)
        if order is None:
            return {"found": False}

        shipment = None
        if order.shipment is not None:
            shipment = {
                "carrier": order.shipment.carrier,
                "tracking_number": order.shipment.tracking_number,
                "status": order.shipment.status.value,
                "estimated_delivery_at": self._date(order.shipment.estimated_delivery_at),
                "delivered_at": self._date(order.shipment.delivered_at),
            }
        return {
            "found": True,
            "order_number": order.order_number,
            "status": order.status.value,
            "payment_status": order.payment_status.value,
            "total_amount": str(order.total_amount),
            "items": [
                {
                    "sku": item.product.sku,
                    "name": item.product.name,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                }
                for item in order.items
            ],
            "shipment": shipment,
            "refunds": [
                {
                    "refund_number": refund.refund_number,
                    "status": refund.status.value,
                    "amount": str(refund.amount),
                }
                for refund in order.refunds
            ],
        }

    @staticmethod
    async def _product(session: AsyncSession, sku: str) -> dict[str, Any]:
        product = await CatalogService(session).get_product_by_sku(sku)
        if product is None:
            return {"found": False}
        return {
            "found": True,
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "unit_price": str(product.unit_price),
            "is_active": product.is_active,
        }

    async def _refund(
        self, session: AsyncSession, user_id: UUID, refund_number: str
    ) -> dict[str, Any]:
        refund = await RefundService(session).get_refund_by_number(refund_number)
        if refund is None:
            return {"found": False}
        orders = await OrderService(session).list_user_orders(user_id)
        if refund.order_id not in {order.id for order in orders}:
            return {"found": False}

        review = None
        if refund.human_review is not None:
            review = {
                "status": refund.human_review.status.value,
                "priority": refund.human_review.priority.value,
            }
        return {
            "found": True,
            "refund_number": refund.refund_number,
            "amount": str(refund.amount),
            "reason": refund.reason,
            "status": refund.status.value,
            "requested_at": self._date(refund.requested_at),
            "completed_at": self._date(refund.completed_at),
            "human_review": review,
        }

    @staticmethod
    def _date(value: Any) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False)
