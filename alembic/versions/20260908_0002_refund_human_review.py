"""Add refund idempotency and review thread fields.

Revision ID: 20260908_0002
Revises: 20260906_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260908_0002"
down_revision: str | None = "20260906_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refunds", sa.Column("request_key", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_refunds_request_key", "refunds", ["request_key"])
    op.add_column("human_reviews", sa.Column("thread_id", sa.String(80), nullable=True))
    op.create_index("ix_human_reviews_thread_id", "human_reviews", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_human_reviews_thread_id", table_name="human_reviews")
    op.drop_column("human_reviews", "thread_id")
    op.drop_constraint("uq_refunds_request_key", "refunds", type_="unique")
    op.drop_column("refunds", "request_key")
