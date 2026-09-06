from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.health import HealthChecker
from ecommerce_ai_agent.main import create_app

Probe = Callable[[], Awaitable[None]]


async def healthy_probe() -> None:
    return None


def build_test_app():
    settings = Settings(_env_file=None, postgres_password=SecretStr("test-password"))
    checker = HealthChecker(
        {
            "postgres": healthy_probe,
            "redis": healthy_probe,
            "milvus": healthy_probe,
        }
    )
    return create_app(settings=settings, health_checker=checker)


@pytest.mark.asyncio
async def test_chat_returns_stable_mock_response_with_server_conversation_id() -> None:
    transport = httpx.ASGITransport(app=build_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "我的订单什么时候到？"})

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"conversation_id", "message", "status", "mode"}
    UUID(payload["conversation_id"])
    assert payload["status"] == "completed"
    assert payload["mode"] == "mock"
    assert set(payload["message"]) == {"id", "role", "content", "created_at"}
    UUID(payload["message"]["id"])
    assert payload["message"]["role"] == "assistant"
    assert payload["message"]["content"]
    created_at = datetime.fromisoformat(payload["message"]["created_at"])
    assert created_at.tzinfo == UTC


@pytest.mark.asyncio
async def test_chat_preserves_valid_client_conversation_id_as_correlation_only() -> None:
    conversation_id = uuid4()
    transport = httpx.ASGITransport(app=build_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            json={"message": "继续", "conversation_id": str(conversation_id)},
        )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == str(conversation_id)


@pytest.mark.parametrize(
    ("payload", "invalid_field"),
    [
        ({"message": ""}, "body.message"),
        ({"message": "   \n\t"}, "body.message"),
        ({"message": "x" * 4001}, "body.message"),
        ({"message": 42}, "body.message"),
        ({"message": "hello", "user_id": "untrusted"}, "body.user_id"),
        ({"message": "hello", "conversation_id": "not-a-uuid"}, "body.conversation_id"),
    ],
)
@pytest.mark.asyncio
async def test_chat_rejects_invalid_input_with_stable_error(
    payload: dict[str, object],
    invalid_field: str,
) -> None:
    transport = httpx.ASGITransport(app=build_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json=payload)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "Request validation failed"
    assert any(detail["field"] == invalid_field for detail in error["details"])


@pytest.mark.asyncio
async def test_chat_rejects_malformed_json_without_echoing_request_body() -> None:
    malformed_body = '{"message": "secret text"'
    transport = httpx.ASGITransport(app=build_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat",
            content=malformed_body,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert malformed_body not in response.text
