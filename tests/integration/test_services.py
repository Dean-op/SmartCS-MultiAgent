from decimal import Decimal

import pytest

from ecommerce_ai_agent.models import Order, Product, User
from ecommerce_ai_agent.models.enums import RefundStatus, ReviewStatus, ShipmentStatus
from ecommerce_ai_agent.services.catalog import CatalogService
from ecommerce_ai_agent.services.data_types import OrderData, ProductData, RefundData, UserData
from ecommerce_ai_agent.services.order import OrderService
from ecommerce_ai_agent.services.refund import RefundService
from ecommerce_ai_agent.services.user import UserService
from tests.integration.conftest import IntegrationDatabase


@pytest.mark.asyncio
async def test_user_and_catalog_services_return_dtos_without_sensitive_or_orm_state(
    seeded_database: IntegrationDatabase,
) -> None:
    async with seeded_database.session_factory() as session:
        user = await UserService(session).get_user_by_email("ALICE@EXAMPLE.COM")
        product = await CatalogService(session).get_product_by_sku("ELEC-HUB-001")

    assert isinstance(user, UserData)
    assert not isinstance(user, User)
    assert user.email == "alice@example.com"
    assert not hasattr(user, "password_hash")
    assert isinstance(product, ProductData)
    assert not isinstance(product, Product)
    assert product.sku == "ELEC-HUB-001"
    assert product.unit_price == Decimal("299.00")


@pytest.mark.asyncio
async def test_order_service_loads_items_products_shipment_and_refunds_after_session_closes(
    seeded_database: IntegrationDatabase,
) -> None:
    async with seeded_database.session_factory() as session:
        order = await OrderService(session).get_order_by_number("EC2026080020")

    assert isinstance(order, OrderData)
    assert not isinstance(order, Order)
    assert order.order_number == "EC2026080020"
    assert order.items
    assert all(item.product.sku for item in order.items)
    assert sum((item.line_total for item in order.items), Decimal("0.00")) == order.total_amount
    assert order.shipment is not None
    assert order.shipment.status == ShipmentStatus.DELIVERED
    assert len(order.refunds) == 1
    assert order.refunds[0].status == RefundStatus.COMPLETED


@pytest.mark.asyncio
async def test_order_ownership_is_scoped_in_service_query(
    seeded_database: IntegrationDatabase,
) -> None:
    async with seeded_database.session_factory() as session:
        users = UserService(session)
        orders = OrderService(session)
        alice = await users.get_user_by_email("alice@example.com")
        bob = await users.get_user_by_email("bob@example.com")
        assert alice is not None and bob is not None
        owned = await orders.get_order_for_user(alice.id, "EC2026080001")
        not_owned = await orders.get_order_for_user(bob.id, "EC2026080001")
        alice_orders = await orders.list_user_orders(alice.id)

    assert owned is not None
    assert owned.user_id == alice.id
    assert not_owned is None
    assert len(alice_orders) == 5
    assert all(order.user_id == alice.id for order in alice_orders)


@pytest.mark.asyncio
async def test_refund_service_loads_optional_human_review(
    seeded_database: IntegrationDatabase,
) -> None:
    async with seeded_database.session_factory() as session:
        refund = await RefundService(session).get_refund_by_number("RF2026080003")
        missing = await RefundService(session).get_refund_by_number("RF-NOT-FOUND")

    assert isinstance(refund, RefundData)
    assert refund.status == RefundStatus.APPROVED
    assert refund.human_review is not None
    assert refund.human_review.status == ReviewStatus.APPROVED
    assert refund.human_review.reviewer_id is not None
    assert missing is None


@pytest.mark.asyncio
async def test_services_support_id_lookups_and_order_refund_listing(
    seeded_database: IntegrationDatabase,
) -> None:
    async with seeded_database.session_factory() as session:
        users = UserService(session)
        catalog = CatalogService(session)
        orders = OrderService(session)
        refunds = RefundService(session)

        user_by_email = await users.get_user_by_email("alice@example.com")
        product_by_sku = await catalog.get_product_by_sku("ELEC-HUB-001")
        order = await orders.get_order_by_number("EC2026080018")
        assert user_by_email is not None
        assert product_by_sku is not None
        assert order is not None

        user_by_id = await users.get_user(user_by_email.id)
        product_by_id = await catalog.get_product(product_by_sku.id)
        order_refunds = await refunds.list_order_refunds(order.id)

    assert user_by_id == user_by_email
    assert product_by_id == product_by_sku
    assert len(order_refunds) == 1
    assert order_refunds[0].order_id == order.id


@pytest.mark.asyncio
async def test_order_dto_does_not_expose_mutable_orm_collections(
    seeded_database: IntegrationDatabase,
) -> None:
    async with seeded_database.session_factory() as session:
        order = await OrderService(session).get_order_by_number("EC2026080020")

    assert order is not None
    with pytest.raises(AttributeError):
        order.items.append(order.items[0])
