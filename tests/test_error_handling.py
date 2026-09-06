import httpx
import pytest
from pydantic import SecretStr

from ecommerce_ai_agent.api.errors import ApplicationError
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.health import HealthChecker
from ecommerce_ai_agent.main import create_app


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
    application = create_app(settings=settings, health_checker=checker)

    @application.get("/_test/application-error")
    async def raise_application_error() -> None:
        raise ApplicationError(
            code="chat_input_error",
            message="The chat input cannot be processed",
            status_code=400,
        )

    @application.get("/_test/unexpected-error")
    async def raise_unexpected_error() -> None:
        raise RuntimeError("internal-sensitive-detail")

    return application


@pytest.mark.asyncio
async def test_not_found_uses_stable_error_contract() -> None:
    transport = httpx.ASGITransport(app=build_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/missing-resource")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Resource not found",
            "details": [],
        }
    }


@pytest.mark.asyncio
async def test_method_not_allowed_uses_stable_error_contract() -> None:
    transport = httpx.ASGITransport(app=build_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/chat")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.asyncio
async def test_application_error_preserves_public_code_and_message() -> None:
    transport = httpx.ASGITransport(app=build_test_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/_test/application-error")

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "chat_input_error",
            "message": "The chat input cannot be processed",
            "details": [],
        }
    }


@pytest.mark.asyncio
async def test_unexpected_error_returns_generic_response_without_internal_details() -> None:
    transport = httpx.ASGITransport(app=build_test_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/_test/unexpected-error")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "An unexpected error occurred",
            "details": [],
        }
    }
    assert "internal-sensitive-detail" not in response.text
