"""Add conversation history and knowledge documents.

Revision ID: 20260908_0003
Revises: 20260908_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260908_0003"
down_revision: str | None = "20260908_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

message_role = postgresql.ENUM(
    "user", "assistant", name="conversation_message_role", create_type=False
)
message_status = postgresql.ENUM(
    "pending",
    "completed",
    "pending_review",
    "failed",
    "cancelled",
    name="conversation_message_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    message_role.create(bind, checkfirst=True)
    message_status.create(bind, checkfirst=True)
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("last_message_preview", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_conversations_title_not_blank"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_conversations_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_user_updated_at", "conversations", ["user_id", "updated_at"])
    op.create_table(
        "conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("reasoning_content", sa.Text(), nullable=True),
        sa.Column("status", message_status, nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("trace_id", sa.String(32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_conversation_messages_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_messages"),
    )
    op.create_index(
        "ix_conversation_messages_conversation_created_at",
        "conversation_messages",
        ["conversation_id", "created_at"],
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("indexed_hash", sa.String(64), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0", name="ck_knowledge_documents_title_not_blank"
        ),
        sa.CheckConstraint(
            "length(btrim(content)) > 0", name="ck_knowledge_documents_content_not_blank"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_documents"),
        sa.UniqueConstraint("source", name="uq_knowledge_documents_source"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_documents")
    op.drop_index(
        "ix_conversation_messages_conversation_created_at",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_user_updated_at", table_name="conversations")
    op.drop_table("conversations")
    bind = op.get_bind()
    message_status.drop(bind, checkfirst=True)
    message_role.drop(bind, checkfirst=True)
