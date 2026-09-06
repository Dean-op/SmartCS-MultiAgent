from decimal import Decimal

import pytest
from sqlalchemy import func, select

from ecommerce_ai_agent.models import HumanReview, Order, OrderItem, Product, Refund, Shipment, User
from ecommerce_ai_agent.models.enums import OrderStatus, UserRole
from ecommerce_ai_agent.seed import SeedCounts, seed_database
from tests.integration.conftest import IntegrationDatabase


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_covers_required_business_scenarios(
    test_database: IntegrationDatabase,
) -> None:
    async with test_database.session_factory.begin() as session:
        first_counts = await seed_database(session)
    async with test_database.session_factory.begin() as session:
        second_counts = await seed_database(session)

    expected = SeedCounts(users=6, products=12, orders=24, shipments=12, refunds=5, reviews=3)
    assert first_counts == expected
    assert second_counts == expected

    async with test_database.session_factory() as session:
        order_status_rows = await session.execute(
            select(Order.status, func.count()).group_by(Order.status)
        )
        order_status_counts = dict(order_status_rows.tuples().all())
        customer_order_rows = await session.execute(
            select(User.email, func.count(Order.id))
            .join(Order, Order.user_id == User.id, isouter=True)
            .where(User.role == UserRole.CUSTOMER)
            .group_by(User.email)
        )
        customer_order_counts = dict(customer_order_rows.tuples().all())
        sample_price = await session.scalar(select(Product.unit_price).limit(1))
        mismatched_totals = await session.scalar(
            select(func.count())
            .select_from(Order)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .group_by(Order.id, Order.total_amount)
            .having(Order.total_amount != func.sum(OrderItem.line_total))
        )
        oversized_refunds = await session.scalar(
            select(func.count())
            .select_from(Refund)
            .join(Order, Refund.order_id == Order.id)
            .where(Refund.amount > Order.total_amount)
        )
        entity_counts = {
            "users": await session.scalar(select(func.count()).select_from(User)),
            "products": await session.scalar(select(func.count()).select_from(Product)),
            "orders": await session.scalar(select(func.count()).select_from(Order)),
            "shipments": await session.scalar(select(func.count()).select_from(Shipment)),
            "refunds": await session.scalar(select(func.count()).select_from(Refund)),
            "reviews": await session.scalar(select(func.count()).select_from(HumanReview)),
        }

    assert entity_counts == {
        "users": 6,
        "products": 12,
        "orders": 24,
        "shipments": 12,
        "refunds": 5,
        "reviews": 3,
    }
    assert order_status_counts == {
        OrderStatus.PENDING_PAYMENT: 4,
        OrderStatus.PROCESSING: 5,
        OrderStatus.SHIPPED: 5,
        OrderStatus.COMPLETED: 7,
        OrderStatus.CANCELLED: 3,
    }
    assert all(count >= 4 for count in customer_order_counts.values())
    assert len(customer_order_counts) == 5
    assert isinstance(sample_price, Decimal)
    assert mismatched_totals is None
    assert oversized_refunds == 0
