from collections.abc import Awaitable, Callable

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
async def test_openapi_describes_versioned_chat_contract_and_error_responses() -> None:
    transport = httpx.ASGITransport(app=build_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "ecommerce-ai-agent"
    assert schema["info"]["version"] == "0.1.0"
    assert "M17" in schema["info"]["description"]

    operation = schema["paths"]["/api/v1/chat"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ChatRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ChatResponse"
    }
    for status_code in ("400", "422", "500", "502", "503", "504"):
        assert operation["responses"][status_code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }

    request_properties = schema["components"]["schemas"]["ChatRequest"]["properties"]
    assert set(request_properties) == {"message", "conversation_id", "client_message_id"}
    mode_schema = schema["components"]["schemas"]["ChatResponse"]["properties"]["mode"]
    assert mode_schema["const"] == "llm"


@pytest.mark.asyncio
async def test_swagger_ui_is_available_at_docs() -> None:
    transport = httpx.ASGITransport(app=build_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text
