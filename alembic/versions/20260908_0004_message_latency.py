"""Add conversation message latency.

Revision ID: 20260908_0004
Revises: 20260908_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260908_0004"
down_revision: str | None = "20260908_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversation_messages", sa.Column("latency_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_messages", "latency_ms")
