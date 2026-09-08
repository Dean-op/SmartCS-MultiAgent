from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.health import HealthChecker
from ecommerce_ai_agent.main import create_app
from ecommerce_ai_agent.schemas.chat import AssistantMessage, ChatResponse
from tests.integration.conftest import IntegrationDatabase


class FakeChatService:
    def __init__(self) -> None:
        self.user_ids: list[UUID] = []

    async def respond(self, request, user_id: UUID) -> ChatResponse:
        self.user_ids.append(user_id)
        return ChatResponse(
            conversation_id=request.conversation_id or uuid4(),
            message=AssistantMessage(id=uuid4(), content="ok", created_at=datetime.now(UTC)),
        )

    async def close(self) -> None:
        return None


def auth_app(database: IntegrationDatabase):
    settings = Settings(
        _env_file=None,
        postgres_password=SecretStr("test-password"),
        jwt_secret=SecretStr("integration-secret-at-least-32-bytes-long"),
    )
    chat = FakeChatService()
    app = create_app(settings=settings, health_checker=HealthChecker({}), chat_service=chat)
    app.state.database = database.database
    return app, chat


@pytest.mark.asyncio
async def test_login_issues_jwt_and_authenticated_chat_receives_current_user(
    seeded_database: IntegrationDatabase,
) -> None:
    app, chat = auth_app(seeded_database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "customer-password"},
        )
        token = login.json()["access_token"]
        response = await client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "你好"},
        )

    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    assert response.status_code == 200
    assert chat.user_ids == [UUID("d15e19f4-bf9f-5e6e-a364-ab4a0f1998a7")]


@pytest.mark.asyncio
async def test_login_and_chat_reject_invalid_credentials(
    seeded_database: IntegrationDatabase,
) -> None:
    app, _ = auth_app(seeded_database)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        bad_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "wrong"},
        )
        no_token = await client.post("/api/v1/chat", json={"message": "你好"})

    assert bad_login.status_code == 401
    assert no_token.status_code == 401
