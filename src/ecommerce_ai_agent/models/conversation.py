from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ecommerce_ai_agent.models.base import Base, TimestampMixin
from ecommerce_ai_agent.models.enums import ConversationMessageRole, ConversationMessageStatus
from ecommerce_ai_agent.models.types import database_enum

if TYPE_CHECKING:
    from ecommerce_ai_agent.models.user import User


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="ck_conversations_title_not_blank"),
        Index("ix_conversations_user_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    last_message_preview: Mapped[str] = mapped_column(String(200), nullable=False)

    user: Mapped[User] = relationship(back_populates="conversations", lazy="raise")
    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="raise"
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conversation_messages_conversation_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[ConversationMessageRole] = mapped_column(
        database_enum(ConversationMessageRole, "conversation_message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reasoning_content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ConversationMessageStatus] = mapped_column(
        database_enum(ConversationMessageStatus, "conversation_message_status"), nullable=False
    )
    request_id: Mapped[str | None] = mapped_column(String(128))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages", lazy="raise")
