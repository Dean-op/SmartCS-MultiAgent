import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from starlette.requests import Request

from ecommerce_ai_agent.api.v1.chat import stream_chat
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.health import HealthChecker
from ecommerce_ai_agent.knowledge import SearchResult
from ecommerce_ai_agent.main import create_app
from ecommerce_ai_agent.observability import record_model_call
from ecommerce_ai_agent.schemas.chat import AssistantMessage, ChatRequest, ChatResponse
from ecommerce_ai_agent.seed import seed_id
from ecommerce_ai_agent.services.conversation import ConversationService
from ecommerce_ai_agent.services.user import UserService
from tests.integration.conftest import IntegrationDatabase


class FakeChat:
    def __init__(self) -> None:
        self.respond_calls = 0

    async def respond(self, request, user_id):
        self.respond_calls += 1
        return ChatResponse(
            conversation_id=request.conversation_id or uuid4(),
            message=AssistantMessage(id=uuid4(), content="ok", created_at=datetime.now(UTC)),
        )

    async def close(self):
        return None

    async def stream_events(self, request, user_id):
        yield {"event": "conversation", "conversation_id": str(request.conversation_id)}
        record_model_call(input_tokens=10, output_tokens=2)
        yield {"event": "status", "phase": "router", "name": "general"}
        yield {"event": "reasoning_delta", "content": "先理解"}
        yield {"event": "delta", "content": "你好"}
        if request.message == "触发取消":
            await asyncio.Event().wait()
        if request.message == "触发流错误":
            raise RuntimeError("sensitive stream failure")
        yield {
            "event": "done",
            "conversation_id": str(request.conversation_id),
            "status": "completed",
            "reasoning_content": "先理解",
            "content": "你好",
            "created_at": datetime.now(UTC).isoformat(),
        }


class FakeKnowledge:
    def __init__(self) -> None:
        self.ingested = []

    async def ingest(self, chunks, *, rebuild=False):
        self.ingested = list(chunks)
        return len(chunks)

    async def search(self, query):
        return [SearchResult("chunk-1", "refund-policy.md", "七天内可申请", 0.91)]


def build_app(database: IntegrationDatabase):
    settings = Settings(
        _env_file=None,
        postgres_password=SecretStr("test-password"),
        jwt_secret=SecretStr("integration-secret-at-least-32-bytes-long"),
    )
    chat = FakeChat()
    app = create_app(settings=settings, health_checker=HealthChecker({}), chat_service=chat)
    app.state.database = database.database
    app.state.knowledge_base = FakeKnowledge()
    app.state.fake_chat = chat
    return app


async def token(client: httpx.AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_me_and_conversation_history_are_owned(
    seeded_database: IntegrationDatabase,
) -> None:
    conversation_id = uuid4()
    async with seeded_database.session_factory.begin() as session:
        turn = await ConversationService(session).start_turn(
            seed_id("user:alice@example.com"), conversation_id, "我的订单"
        )
        assert turn is not None

    app = build_app(seeded_database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        alice_token = await token(client, "alice@example.com", "customer-password")
        other_token = await token(client, "admin@example.com", "admin-password")
        me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {alice_token}"})
        conversations = await client.get(
            "/api/v1/conversations", headers={"Authorization": f"Bearer {alice_token}"}
        )
        history = await client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        forbidden = await client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers={"Authorization": f"Bearer {other_token}"},
        )

    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"
    assert me.json()["role"] == "customer"
    assert str(conversation_id) in {
        item["conversation_id"] for item in conversations.json()["items"]
    }
    assert [item["role"] for item in history.json()["items"]] == ["user", "assistant"]
    assert forbidden.status_code == 404


@pytest.mark.asyncio
async def test_knowledge_admin_crud_rebuild_search_and_customer_denial(
    seeded_database: IntegrationDatabase,
) -> None:
    app = build_app(seeded_database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        customer_token = await token(client, "alice@example.com", "customer-password")
        admin_token = await token(client, "admin@example.com", "admin-password")
        denied = await client.get(
            "/api/v1/knowledge/documents",
            headers={"Authorization": f"Bearer {customer_token}"},
        )
        created = await client.post(
            "/api/v1/knowledge/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"title": "退款测试", "source": "api-refund-test.md", "content": "# 七天退款"},
        )
        document_id = created.json()["id"]
        rebuilt = await client.post(
            "/api/v1/knowledge/rebuild",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        searched = await client.post(
            "/api/v1/knowledge/search",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"query": "退款期限"},
        )
        deleted = await client.delete(
            f"/api/v1/knowledge/documents/{document_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert denied.status_code == 403
    assert created.status_code == 201
    assert created.json()["is_indexed"] is False
    assert rebuilt.status_code == 200
    assert rebuilt.json()["documents"] >= 1
    assert rebuilt.json()["chunks"] >= 1
    assert searched.json()["items"][0]["source"] == "refund-policy.md"
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_existing_chat_endpoint_persists_messages_for_history(
    seeded_database: IntegrationDatabase,
) -> None:
    app = build_app(seeded_database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        access_token = await token(client, "alice@example.com", "customer-password")
        chat = await client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"message": "请记录这次对话"},
        )
        history = await client.get(
            f"/api/v1/conversations/{chat.json()['conversation_id']}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert chat.status_code == 200
    assert [(item["role"], item["content"]) for item in history.json()["items"]] == [
        ("user", "请记录这次对话"),
        ("assistant", "ok"),
    ]


@pytest.mark.asyncio
async def test_sse_chat_streams_reasoning_answer_and_persists_both(
    seeded_database: IntegrationDatabase,
) -> None:
    app = build_app(seeded_database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        access_token = await token(client, "alice@example.com", "customer-password")
        response = await client.post(
            "/api/v1/chat/stream",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "text/event-stream",
            },
            json={"message": "你好"},
        )
        conversation_line = next(
            line for line in response.text.splitlines() if '"conversation_id"' in line
        )
        conversation_id = conversation_line.split('"conversation_id":"')[1].split('"')[0]
        history = await client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: reasoning_delta" in response.text
    assert 'data: {"content":"先理解"}' in response.text
    assert "event: delta" in response.text
    assert "event: done" in response.text
    assistant = history.json()["items"][-1]
    assert assistant["content"] == "你好"
    assert assistant["reasoning_content"] == "先理解"
    assert assistant["status"] == "completed"


@pytest.mark.asyncio
async def test_request_observation_finishes_after_sse_body(caplog, seeded_database) -> None:
    app = build_app(seeded_database)
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level(logging.INFO, logger="ecommerce_ai_agent.observability"):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            access_token = await token(client, "alice@example.com", "customer-password")
            await client.post(
                "/api/v1/chat/stream",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"message": "你好"},
            )

    record = next(
        record
        for record in caplog.records
        if record.message == "Request completed" and record.http_path == "/api/v1/chat/stream"
    )
    assert record.model_calls == 1
    assert record.input_tokens == 10
    assert record.output_tokens == 2


@pytest.mark.asyncio
async def test_sse_error_is_observed_and_preserves_partial_output(caplog, seeded_database) -> None:
    app = build_app(seeded_database)
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            access_token = await token(client, "alice@example.com", "customer-password")
            response = await client.post(
                "/api/v1/chat/stream",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"message": "触发流错误"},
            )
            conversation_line = next(
                line for line in response.text.splitlines() if '"conversation_id"' in line
            )
            conversation_id = conversation_line.split('"conversation_id":"')[1].split('"')[0]
            history = await client.get(
                f"/api/v1/conversations/{conversation_id}/messages",
                headers={"Authorization": f"Bearer {access_token}"},
            )

    assistant = history.json()["items"][-1]
    assert "event: error" in response.text
    assert assistant["content"] == "你好"
    assert assistant["reasoning_content"] == "先理解"
    assert assistant["status"] == "failed"
    assert any(record.message == "SSE chat failed" for record in caplog.records)
    summary = next(
        record
        for record in caplog.records
        if record.message == "Request completed" and record.http_path == "/api/v1/chat/stream"
    )
    assert summary.error_count == 1


@pytest.mark.asyncio
async def test_duplicate_client_message_id_replays_without_second_model_call(
    seeded_database: IntegrationDatabase,
) -> None:
    app = build_app(seeded_database)
    transport = httpx.ASGITransport(app=app)
    conversation_id = uuid4()
    client_message_id = uuid4()
    payload = {
        "message": "幂等消息",
        "conversation_id": str(conversation_id),
        "client_message_id": str(client_message_id),
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        access_token = await token(client, "alice@example.com", "customer-password")
        headers = {"Authorization": f"Bearer {access_token}"}
        first = await client.post("/api/v1/chat", headers=headers, json=payload)
        second = await client.post(
            "/api/v1/chat",
            headers=headers,
            json={"message": "幂等消息", "client_message_id": str(client_message_id)},
        )
        history = await client.get(
            f"/api/v1/conversations/{conversation_id}/messages", headers=headers
        )

    assert first.status_code == second.status_code == 200
    assert first.json()["message"]["id"] == second.json()["message"]["id"]
    assert app.state.fake_chat.respond_calls == 1
    assert len(history.json()["items"]) == 2


@pytest.mark.asyncio
async def test_cancelled_sse_persists_partial_reasoning_and_answer(
    seeded_database: IntegrationDatabase,
) -> None:
    app = build_app(seeded_database)
    async with seeded_database.session_factory() as session:
        user = await UserService(session).get_user_by_email("alice@example.com")
    assert user is not None
    request = Request({"type": "http", "app": app, "headers": []})
    response = await stream_chat(
        ChatRequest(message="触发取消"), request, app.state.fake_chat, user
    )
    iterator = response.body_iterator.__aiter__()
    first_chunk = await anext(iterator)
    conversation_id = json.loads(first_chunk.split("data: ", 1)[1])["conversation_id"]
    for _ in range(3):
        await anext(iterator)
    pending = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0.01)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    async with seeded_database.session_factory() as session:
        messages = await ConversationService(session).list_messages(user.id, UUID(conversation_id))

    assert messages is not None
    assert messages[-1].content == "你好"
    assert messages[-1].reasoning_content == "先理解"
    assert messages[-1].status.value == "cancelled"
