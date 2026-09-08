from uuid import uuid4

import pytest

from ecommerce_ai_agent.models.enums import ConversationMessageStatus
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
