"""Create the M2 business schema.

Revision ID: 20260906_0001
Revises:
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260906_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = postgresql.ENUM("customer", "admin", name="user_role", create_type=False)
order_status = postgresql.ENUM(
    "pending_payment",
    "processing",
    "shipped",
    "completed",
    "cancelled",
    name="order_status",
    create_type=False,
)
payment_status = postgresql.ENUM(
    "unpaid",
    "paid",
    "partially_refunded",
    "refunded",
    name="payment_status",
    create_type=False,
)
shipment_status = postgresql.ENUM(
    "pending",
    "in_transit",
    "delivered",
    "exception",
    name="shipment_status",
    create_type=False,
)
refund_status = postgresql.ENUM(
    "requested",
    "pending_review",
    "approved",
    "rejected",
    "processing",
    "completed",
    "cancelled",
    name="refund_status",
    create_type=False,
)
review_status = postgresql.ENUM(
    "pending", "approved", "rejected", name="review_status", create_type=False
)
review_priority = postgresql.ENUM("normal", "high", name="review_priority", create_type=False)

enum_types = (
    user_role,
    order_status,
    payment_status,
    shipment_status,
    refund_status,
    review_status,
    review_priority,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in enum_types:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("role", user_role, server_default="customer", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(btrim(email)) > 0", name="ck_users_email_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_products_name_not_blank"),
        sa.CheckConstraint("length(btrim(sku)) > 0", name="ck_products_sku_not_blank"),
        sa.CheckConstraint("unit_price >= 0", name="ck_products_unit_price_non_negative"),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", order_status, nullable=False),
        sa.Column("payment_status", payment_status, nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(btrim(order_number)) > 0", name="ck_orders_order_number_not_blank"
        ),
        sa.CheckConstraint("total_amount >= 0", name="ck_orders_total_amount_non_negative"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_orders_user_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.UniqueConstraint("order_number", name="uq_orders_order_number"),
    )
    op.create_index("ix_orders_user_created_at", "orders", ["user_id", "created_at"])

    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("line_total >= 0", name="ck_order_items_line_total_non_negative"),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price_non_negative"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_order_items_order_id_orders", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_order_items_product_id_products",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_items"),
        sa.UniqueConstraint("order_id", "product_id", name="uq_order_items_order_product"),
    )

    op.create_table(
        "shipments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("carrier", sa.String(length=100), nullable=False),
        sa.Column("tracking_number", sa.String(length=100), nullable=False),
        sa.Column("status", shipment_status, nullable=False),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(btrim(carrier)) > 0", name="ck_shipments_carrier_not_blank"),
        sa.CheckConstraint(
            "length(btrim(tracking_number)) > 0", name="ck_shipments_tracking_number_not_blank"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_shipments_order_id_orders", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shipments"),
        sa.UniqueConstraint("carrier", "tracking_number", name="uq_shipments_carrier_tracking"),
        sa.UniqueConstraint("order_id", name="uq_shipments_order_id"),
    )

    op.create_table(
        "refunds",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("refund_number", sa.String(length=32), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("status", refund_status, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_refunds_reason_not_blank"),
        sa.CheckConstraint(
            "length(btrim(refund_number)) > 0", name="ck_refunds_refund_number_not_blank"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_refunds_order_id_orders", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refunds"),
        sa.UniqueConstraint("refund_number", name="uq_refunds_refund_number"),
    )
    op.create_index("ix_refunds_order_created_at", "refunds", ["order_id", "created_at"])

    op.create_table(
        "human_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("refund_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", review_status, server_default="pending", nullable=False),
        sa.Column("priority", review_priority, server_default="normal", nullable=False),
        sa.Column("reviewer_note", sa.String(length=1000), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["refund_id"],
            ["refunds.id"],
            name="fk_human_reviews_refund_id_refunds",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name="fk_human_reviews_reviewer_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_human_reviews"),
        sa.UniqueConstraint("refund_id", name="uq_human_reviews_refund_id"),
    )


def downgrade() -> None:
    op.drop_table("human_reviews")
    op.drop_index("ix_refunds_order_created_at", table_name="refunds")
    op.drop_table("refunds")
    op.drop_table("shipments")
    op.drop_table("order_items")
    op.drop_index("ix_orders_user_created_at", table_name="orders")
    op.drop_table("orders")
    op.drop_table("products")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    for enum_type in reversed(enum_types):
        enum_type.drop(bind, checkfirst=True)
