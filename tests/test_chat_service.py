from uuid import uuid4

import pytest

from ecommerce_ai_agent.schemas.chat import ChatRequest
from ecommerce_ai_agent.services.chat import ChatService


class RecordingModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return "可以提供一般建议，但目前无法查询真实订单。"

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_chat_service_uses_guardrails_and_preserves_conversation_id() -> None:
    conversation_id = uuid4()
    model = RecordingModel()
    service = ChatService(model)

    response = await service.respond(
        ChatRequest(message="查询订单 A1001", conversation_id=conversation_id)
    )

    system_prompt, user_prompt = model.calls[0]
    assert "不能声称已经查询" in system_prompt
    assert "不能声称已经修改" in system_prompt
    assert "不能声称已经创建退款" in system_prompt
    assert user_prompt == "查询订单 A1001"
    assert response.conversation_id == conversation_id
    assert response.message.content == "可以提供一般建议，但目前无法查询真实订单。"
    assert response.mode == "llm"


@pytest.mark.asyncio
async def test_chat_service_closes_model_client() -> None:
    model = RecordingModel()
    service = ChatService(model)

    await service.close()

    assert model.closed is True
