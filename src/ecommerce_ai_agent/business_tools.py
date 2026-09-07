import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ecommerce_ai_agent.services.catalog import CatalogService
from ecommerce_ai_agent.services.order import OrderService
from ecommerce_ai_agent.services.refund import RefundService
from ecommerce_ai_agent.services.user import UserService

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
]


class BusinessTools:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        trusted_user_email: str,
    ) -> None:
        self._session_factory = session_factory
        self._trusted_user_email = trusted_user_email

    async def run(self, name: str, arguments: str) -> str:
        try:
            async with self._session_factory() as session:
                match name:
                    case "get_current_user_order":
                        parsed = OrderArguments.model_validate_json(arguments)
                        result = await self._order(session, parsed.order_number)
                    case "get_product_by_sku":
                        parsed = ProductArguments.model_validate_json(arguments)
                        result = await self._product(session, parsed.sku)
                    case "get_current_user_refund":
                        parsed = RefundArguments.model_validate_json(arguments)
                        result = await self._refund(session, parsed.refund_number)
                    case _:
                        return self._json({"error": "unknown_tool"})
        except ValidationError:
            return self._json({"error": "invalid_arguments"})

        logger.info("Business tool executed", extra={"tool_name": name})
        return self._json(result)

    async def _order(self, session: AsyncSession, order_number: str) -> dict[str, Any]:
        user = await UserService(session).get_user_by_email(self._trusted_user_email)
        if user is None or not user.is_active:
            return {"found": False}
        order = await OrderService(session).get_order_for_user(user.id, order_number)
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

    async def _refund(self, session: AsyncSession, refund_number: str) -> dict[str, Any]:
        user = await UserService(session).get_user_by_email(self._trusted_user_email)
        if user is None or not user.is_active:
            return {"found": False}
        refund = await RefundService(session).get_refund_by_number(refund_number)
        if refund is None:
            return {"found": False}
        orders = await OrderService(session).list_user_orders(user.id)
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
