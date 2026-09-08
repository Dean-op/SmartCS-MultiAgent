import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from sqlalchemy import select

from ecommerce_ai_agent.business_tools import BusinessTools
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.health import HealthChecker
from ecommerce_ai_agent.llm.client import ModelTurn, ToolCall
from ecommerce_ai_agent.main import create_app
from ecommerce_ai_agent.models import HumanReview, Order, Refund
from ecommerce_ai_agent.models.enums import RefundStatus, ReviewPriority
from ecommerce_ai_agent.schemas.chat import AssistantMessage, ChatResponse
from ecommerce_ai_agent.services.chat import ChatService
from ecommerce_ai_agent.services.refund import RefundService
from tests.integration.conftest import IntegrationDatabase


class ReviewChatService:
    def __init__(self) -> None:
        self.resumes: list[tuple[str, UUID, str, UUID, str | None]] = []

    async def respond(self, request, user_id):
        raise AssertionError("chat is not used in review API tests")

    async def resume_review(
        self,
        thread_id: str,
        conversation_id: UUID,
        decision: str,
        reviewer_id: UUID,
        note: str | None,
    ) -> ChatResponse:
        self.resumes.append((thread_id, conversation_id, decision, reviewer_id, note))
        return ChatResponse(
            conversation_id=conversation_id,
            message=AssistantMessage(
                id=uuid4(), content=f"review {decision}", created_at=datetime.now(UTC)
            ),
        )

    async def close(self) -> None:
        return None


class RefundRequestModel:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def generate_structured(self, system_prompt, user_prompt, schema_type):
        return schema_type(route="refund")

    async def generate_turn(self, messages, tools) -> ModelTurn:
        return ModelTurn(
            content=None,
            tool_calls=(
                ToolCall(
                    id="request-refund",
                    name="request_refund",
                    arguments=json.dumps(
                        {
                            "order_number": "EC2026080021",
                            "amount": "150.00",
                            "reason": self.reason,
                        }
                    ),
                ),
            ),
        )

    async def close(self) -> None:
        return None


class EmptyKnowledge:
    async def search(self, question):
        return []

    async def close(self) -> None:
        return None


async def login(client: httpx.AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_review_api_is_admin_only_and_resumes_pending_graph(
    seeded_database: IntegrationDatabase,
) -> None:
    conversation_id = uuid4()
    async with seeded_database.session_factory.begin() as session:
        order = await session.scalar(select(Order).where(Order.order_number == "EC2026080016"))
        assert order is not None
        refund = Refund(
            refund_number=f"RFTEST{uuid4().hex[:12].upper()}",
            request_key=uuid4().hex,
            order_id=order.id,
            amount=Decimal("150.00"),
            reason="API review test",
            status=RefundStatus.PENDING_REVIEW,
            requested_at=datetime.now(UTC),
        )
        review = HumanReview(
            refund=refund,
            thread_id=f"{order.user_id}:{conversation_id}",
            priority=ReviewPriority.HIGH,
        )
        session.add(review)
        await session.flush()
        review_id = review.id

    settings = Settings(
        _env_file=None,
        postgres_password=SecretStr("test-password"),
        jwt_secret=SecretStr("integration-secret-at-least-32-bytes-long"),
    )
    chat = ReviewChatService()
    app = create_app(settings=settings, health_checker=HealthChecker({}), chat_service=chat)
    app.state.database = seeded_database.database
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        customer_token = await login(client, "alice@example.com", "customer-password")
        admin_token = await login(client, "admin@example.com", "admin-password")
        customer = await client.get(
            "/api/v1/reviews/pending",
            headers={"Authorization": f"Bearer {customer_token}"},
        )
        pending = await client.get(
            "/api/v1/reviews/pending",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        approved = await client.post(
            f"/api/v1/reviews/{review_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"note": "同意退款"},
        )

    assert customer.status_code == 403
    assert pending.status_code == 200
    assert str(review_id) in {item["review_id"] for item in pending.json()}
    assert approved.status_code == 200
    assert approved.json()["conversation_id"] == str(conversation_id)
    assert chat.resumes[0][0] == f"{order.user_id}:{conversation_id}"
    assert chat.resumes[0][2:] == ("approve", chat.resumes[0][3], "同意退款")


@pytest.mark.asyncio
async def test_chat_interrupt_and_admin_approve_resume_across_http_requests(
    seeded_database: IntegrationDatabase,
) -> None:
    reason = f"HTTP-HITL-{uuid4()}"
    settings = Settings(
        _env_file=None,
        postgres_password=SecretStr("test-password"),
        jwt_secret=SecretStr("integration-secret-at-least-32-bytes-long"),
    )
    service = ChatService(
        RefundRequestModel(reason),
        BusinessTools(seeded_database.session_factory, settings),
        EmptyKnowledge(),
        checkpointer=InMemorySaver(),
    )
    app = create_app(settings=settings, health_checker=HealthChecker({}), chat_service=service)
    app.state.database = seeded_database.database
    conversation_id = uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        customer_token = await login(client, "alice@example.com", "customer-password")
        admin_token = await login(client, "admin@example.com", "admin-password")
        submitted = await client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {customer_token}"},
            json={"message": "我要申请退款 150 元", "conversation_id": str(conversation_id)},
        )
        pending = await client.get(
            "/api/v1/reviews/pending",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        created = next(item for item in pending.json() if item["reason"] == reason)
        approved = await client.post(
            f"/api/v1/reviews/{created['review_id']}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"note": "证据充分"},
        )

    async with seeded_database.session_factory() as session:
        review = await RefundService(session).get_review(UUID(created["review_id"]))

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pending_review"
    assert approved.status_code == 200
    assert "已通过人工审核并完成" in approved.json()["message"]["content"]
    assert review is not None
    assert review.status.value == "approved"
