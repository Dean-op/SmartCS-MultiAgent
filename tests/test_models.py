from enum import Enum

from sqlalchemy import CheckConstraint, Numeric, UniqueConstraint
from sqlalchemy import Enum as SqlEnum

from ecommerce_ai_agent.models import Base
from ecommerce_ai_agent.models.enums import (
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    ReviewPriority,
    ReviewStatus,
    ShipmentStatus,
    UserRole,
)

EXPECTED_TABLES = {
    "users",
    "products",
    "orders",
    "order_items",
    "shipments",
    "refunds",
    "human_reviews",
}


def enum_values(enum_type: type[Enum]) -> set[str]:
    return {member.value for member in enum_type}


def unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def foreign_key_target(table_name: str, column_name: str) -> str:
    column = Base.metadata.tables[table_name].c[column_name]
    return next(iter(column.foreign_keys)).target_fullname


def test_metadata_contains_only_the_seven_m2_business_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_business_statuses_are_finite_and_use_stable_database_values() -> None:
    assert enum_values(UserRole) == {"customer", "admin"}
    assert enum_values(OrderStatus) == {
        "pending_payment",
        "processing",
        "shipped",
        "completed",
        "cancelled",
    }
    assert enum_values(PaymentStatus) == {"unpaid", "paid", "partially_refunded", "refunded"}
    assert enum_values(ShipmentStatus) == {"pending", "in_transit", "delivered", "exception"}
    assert enum_values(RefundStatus) == {
        "requested",
        "pending_review",
        "approved",
        "rejected",
        "processing",
        "completed",
        "cancelled",
    }
    assert enum_values(ReviewStatus) == {"pending", "approved", "rejected"}
    assert enum_values(ReviewPriority) == {"normal", "high"}

    status_columns = {
        ("users", "role"): "user_role",
        ("orders", "status"): "order_status",
        ("orders", "payment_status"): "payment_status",
        ("shipments", "status"): "shipment_status",
        ("refunds", "status"): "refund_status",
        ("human_reviews", "status"): "review_status",
        ("human_reviews", "priority"): "review_priority",
    }
    for (table_name, column_name), database_type_name in status_columns.items():
        column_type = Base.metadata.tables[table_name].c[column_name].type
        assert isinstance(column_type, SqlEnum)
        assert column_type.native_enum is True
        assert column_type.name == database_type_name


def test_all_money_columns_use_fixed_precision_decimal_types() -> None:
    for table_name, column_name in (
        ("products", "unit_price"),
        ("orders", "total_amount"),
        ("order_items", "unit_price"),
        ("order_items", "line_total"),
        ("refunds", "amount"),
    ):
        column_type = Base.metadata.tables[table_name].c[column_name].type
        assert isinstance(column_type, Numeric)
        assert column_type.precision == 12
        assert column_type.scale == 2
        assert column_type.asdecimal is True


def test_ownership_and_aggregate_relationships_are_enforced_by_foreign_keys() -> None:
    assert foreign_key_target("orders", "user_id") == "users.id"
    assert Base.metadata.tables["orders"].c.user_id.nullable is False
    assert foreign_key_target("order_items", "order_id") == "orders.id"
    assert foreign_key_target("order_items", "product_id") == "products.id"
    assert foreign_key_target("shipments", "order_id") == "orders.id"
    assert foreign_key_target("refunds", "order_id") == "orders.id"
    assert foreign_key_target("human_reviews", "refund_id") == "refunds.id"
    assert foreign_key_target("human_reviews", "reviewer_id") == "users.id"


def test_business_uniqueness_and_range_constraints_cover_real_lookup_keys() -> None:
    assert ("sku",) in unique_column_sets("products")
    assert ("order_number",) in unique_column_sets("orders")
    assert ("order_id", "product_id") in unique_column_sets("order_items")
    assert ("order_id",) in unique_column_sets("shipments")
    assert ("carrier", "tracking_number") in unique_column_sets("shipments")
    assert ("refund_number",) in unique_column_sets("refunds")
    assert ("refund_id",) in unique_column_sets("human_reviews")

    expected_checks = {
        "products": {"ck_products_unit_price_non_negative"},
        "orders": {"ck_orders_total_amount_non_negative"},
        "order_items": {
            "ck_order_items_quantity_positive",
            "ck_order_items_unit_price_non_negative",
            "ck_order_items_line_total_non_negative",
        },
        "refunds": {"ck_refunds_amount_positive"},
    }
    for table_name, names in expected_checks.items():
        constraints = {
            constraint.name
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert names <= constraints


def test_all_timestamp_columns_retain_timezone_information() -> None:
    timestamp_columns = [
        column
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name.endswith("_at")
    ]
    assert timestamp_columns
    assert all(column.type.timezone is True for column in timestamp_columns)
