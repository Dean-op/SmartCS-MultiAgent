from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ecommerce_ai_agent.models import Conversation, ConversationMessage
from ecommerce_ai_agent.models.enums import (
    ConversationMessageRole,
    ConversationMessageStatus,
)
from ecommerce_ai_agent.seed import seed_id
from ecommerce_ai_agent.services.conversation import ConversationService
from ecommerce_ai_agent.services.knowledge_documents import KnowledgeDocumentService
from tests.integration.conftest import IntegrationDatabase


@pytest.mark.asyncio
async def test_conversation_service_persists_owned_turn_and_history(
    seeded_database: IntegrationDatabase,
) -> None:
    conversation_id = uuid4()
    alice_id = seed_id("user:alice@example.com")
    async with seeded_database.session_factory.begin() as session:
        service = ConversationService(session)
        turn = await service.start_turn(alice_id, conversation_id, "查询订单 EC2026080016")
        await service.complete_assistant(
            turn.assistant_message_id,
            content="订单已完成",
            reasoning_content="先确认订单归属",
            status=ConversationMessageStatus.COMPLETED,
            request_id="request-1",
            trace_id="a" * 32,
        )

    async with seeded_database.session_factory() as session:
        service = ConversationService(session)
        conversations = await service.list_conversations(alice_id)
        messages = await service.list_messages(alice_id, conversation_id)

    assert conversations[0].id == conversation_id
    assert conversations[0].title == "查询订单 EC2026080016"
    assert conversations[0].last_message_preview == "订单已完成"
    assert [message.role.value for message in messages] == ["user", "assistant"]
    assert messages[-1].reasoning_content == "先确认订单归属"
    assert messages[-1].request_id == "request-1"


@pytest.mark.asyncio
async def test_conversation_history_does_not_cross_user_boundary(
    seeded_database: IntegrationDatabase,
) -> None:
    conversation_id = uuid4()
    alice_id = seed_id("user:alice@example.com")
    bob_id = seed_id("user:bob@example.com")
    async with seeded_database.session_factory.begin() as session:
        await ConversationService(session).start_turn(alice_id, conversation_id, "我的订单")

    async with seeded_database.session_factory() as session:
        assert await ConversationService(session).list_messages(bob_id, conversation_id) is None


@pytest.mark.asyncio
async def test_knowledge_document_service_tracks_content_needing_rebuild(
    seeded_database: IntegrationDatabase,
) -> None:
    async with seeded_database.session_factory.begin() as session:
        service = KnowledgeDocumentService(session)
        document = await service.create("测试政策", "test-policy.md", "# 初始规则")
        await service.mark_all_indexed()
        indexed = await service.get(document.id)
        assert indexed is not None and indexed.is_indexed
        updated = await service.update(document.id, "测试政策", "test-policy.md", "# 新规则")

    assert updated is not None
    assert not updated.is_indexed
    assert updated.content_hash != updated.indexed_hash

    async with seeded_database.session_factory.begin() as session:
        service = KnowledgeDocumentService(session)
        assert await service.delete(document.id)
        assert await service.get(document.id) is None


@pytest.mark.asyncio
async def test_history_returns_the_latest_two_hundred_messages_in_display_order(
    seeded_database: IntegrationDatabase,
) -> None:
    conversation_id = uuid4()
    user_id = seed_id("user:alice@example.com")
    started = datetime.now(UTC)
    async with seeded_database.session_factory.begin() as session:
        session.add(
            Conversation(
                id=conversation_id,
                user_id=user_id,
                title="长会话",
                last_message_preview="message-201",
            )
        )
        session.add_all(
            [
                ConversationMessage(
                    conversation_id=conversation_id,
                    role=ConversationMessageRole.USER,
                    content=f"message-{index}",
                    status=ConversationMessageStatus.COMPLETED,
                    created_at=started + timedelta(microseconds=index),
                )
                for index in range(202)
            ]
        )

    async with seeded_database.session_factory() as session:
        messages = await ConversationService(session).list_messages(user_id, conversation_id)

    assert messages is not None
    assert len(messages) == 200
    assert messages[0].content == "message-2"
    assert messages[-1].content == "message-201"


@pytest.mark.asyncio
async def test_client_message_id_replays_existing_turn_without_duplicate_rows(
    seeded_database: IntegrationDatabase,
) -> None:
    conversation_id = uuid4()
    client_message_id = uuid4()
    user_id = seed_id("user:alice@example.com")
    async with seeded_database.session_factory.begin() as session:
        service = ConversationService(session)
        first = await service.start_turn(
            user_id,
            conversation_id,
            "同一条消息",
            client_message_id=client_message_id,
        )
        second = await service.start_turn(
            user_id,
            conversation_id,
            "同一条消息",
            client_message_id=client_message_id,
        )

    async with seeded_database.session_factory() as session:
        messages = await ConversationService(session).list_messages(user_id, conversation_id)

    assert first is not None and second is not None
    assert second.replayed
    assert second.user_message_id == first.user_message_id
    assert second.assistant_message_id == first.assistant_message_id
    assert messages is not None and len(messages) == 2


@pytest.mark.asyncio
async def test_review_resolution_replaces_pending_history_message(
    seeded_database: IntegrationDatabase,
) -> None:
    conversation_id = uuid4()
    user_id = seed_id("user:alice@example.com")
    async with seeded_database.session_factory.begin() as session:
        service = ConversationService(session)
        turn = await service.start_turn(user_id, conversation_id, "申请退款")
        assert turn is not None
        await service.complete_assistant(
            turn.assistant_message_id,
            content="正在等待人工审核",
            reasoning_content=None,
            status=ConversationMessageStatus.PENDING_REVIEW,
        )
        await service.resolve_pending_review(conversation_id, "退款已通过人工审核")

    async with seeded_database.session_factory() as session:
        messages = await ConversationService(session).list_messages(user_id, conversation_id)

    assert messages is not None
    assert messages[-1].content == "退款已通过人工审核"
    assert messages[-1].status == ConversationMessageStatus.COMPLETED


@pytest.mark.asyncio
async def test_rebuild_snapshot_does_not_mark_concurrently_edited_document_indexed(
    seeded_database: IntegrationDatabase,
) -> None:
    async with seeded_database.session_factory.begin() as session:
        service = KnowledgeDocumentService(session)
        document = await service.create("竞态测试", "race-policy.md", "# 旧内容")
        snapshot_hash = document.content_hash
        await service.update(document.id, "竞态测试", "race-policy.md", "# 新内容")
        await service.mark_indexed({document.id: snapshot_hash})
        current = await service.get(document.id)

    assert current is not None
    assert not current.is_indexed
    assert current.indexed_hash is None
