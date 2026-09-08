from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from ecommerce_ai_agent.api.dependencies import get_current_user
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.health import HealthChecker
from ecommerce_ai_agent.llm.client import ModelTurn
from ecommerce_ai_agent.main import create_app
from ecommerce_ai_agent.services.chat import ChatService

Probe = Callable[[], Awaitable[None]]


async def healthy_probe() -> None:
    return None


class FakeModel:
    async def generate_structured(self, system_prompt, user_prompt, schema_type):
        return schema_type(route="general")

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        return "来自 Fake Model 的回复"

    async def generate_turn(self, messages, tools) -> ModelTurn:
        return ModelTurn(content="来自 Fake Model 的回复", tool_calls=())

    async def close(self) -> None:
        return None


class FakeTools:
    async def run(self, name: str, arguments: str, user_id) -> str:
        return '{"found":false}'


class FakeKnowledge:
    async def search(self, question: str) -> list:
        return []

    async def close(self) -> None:
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
    application = create_app(
        settings=settings,
        health_checker=checker,
        chat_service=ChatService(FakeModel(), FakeTools(), FakeKnowledge()),
    )
    application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
    return application


@pytest.mark.asyncio
async def test_chat_returns_stable_llm_response_with_server_conversation_id() -> None:
    transport = httpx.ASGITransport(app=build_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "我的订单什么时候到？"})

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"conversation_id", "message", "status", "mode"}
    UUID(payload["conversation_id"])
    assert payload["status"] == "completed"
    assert payload["mode"] == "llm"
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


@pytest.mark.asyncio
async def test_chat_reports_missing_model_configuration_without_breaking_app() -> None:
    settings = Settings(_env_file=None, postgres_password=SecretStr("test-password"))
    checker = HealthChecker(
        {"postgres": healthy_probe, "redis": healthy_probe, "milvus": healthy_probe}
    )
    application = create_app(settings=settings, health_checker=checker)
    transport = httpx.ASGITransport(app=application)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "hello"})

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "model_not_configured",
        "message": "The model provider is not configured",
        "details": [],
    }
