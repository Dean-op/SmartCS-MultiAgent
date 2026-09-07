import logging
from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest
from pydantic import SecretStr

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import (
    ModelAuthenticationError,
    ModelConfigurationError,
    ModelProviderError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredOutputError,
)
from ecommerce_ai_agent.llm.schemas import MessageAssessment


class FakeCompletions:
    def __init__(self, *, content: str | None = "ok", error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any):
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeOpenAI:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def model_settings(**overrides: Any) -> Settings:
    values = {
        "postgres_password": SecretStr("test-password"),
        "dashscope_api_key": SecretStr("test-api-key"),
        "bailian_base_url": "https://example.com/compatible-mode/v1",
        "llm_model": "qwen3.8-27b",
        "llm_timeout_seconds": 12,
        "llm_max_retries": 2,
        "llm_temperature": 0.2,
        "llm_max_completion_tokens": 321,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "missing_field",
    ["dashscope_api_key", "bailian_base_url", "llm_model"],
)
def test_model_requires_complete_provider_configuration(missing_field: str) -> None:
    with pytest.raises(ModelConfigurationError) as captured:
        BailianModel(model_settings(**{missing_field: None}))

    assert captured.value.code == "model_not_configured"
    assert captured.value.status_code == 503


@pytest.mark.asyncio
async def test_text_generation_uses_configured_model_without_tool_calling() -> None:
    completions = FakeCompletions(content="真实模型回复")
    model = BailianModel(model_settings(), client=FakeOpenAI(completions))

    result = await model.generate_text("system rules", "customer message")

    assert result == "真实模型回复"
    request = completions.requests[0]
    assert request["model"] == "qwen3.8-27b"
    assert request["temperature"] == 0.2
    assert request["max_completion_tokens"] == 321
    assert request["messages"] == [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "customer message"},
    ]
    assert "tools" not in request
    assert "tool_choice" not in request


@pytest.mark.asyncio
async def test_structured_generation_returns_validated_typed_result() -> None:
    completions = FakeCompletions(
        content='{"summary":"查询订单状态","requires_business_action":true,"reason":"需要真实订单数据"}'
    )
    model = BailianModel(model_settings(), client=FakeOpenAI(completions))

    result = await model.generate_structured(
        "Assess customer requests.",
        "请查询订单 A1001",
        MessageAssessment,
    )

    assert isinstance(result, MessageAssessment)
    assert result.requires_business_action is True
    request = completions.requests[0]
    assert request["response_format"] == {"type": "json_object"}
    structured_prompt = request["messages"][0]["content"]
    assert "JSON Schema" in structured_prompt
    assert "requires_business_action" in structured_prompt
    assert "additionalProperties" in structured_prompt
    assert request["extra_body"] == {"enable_thinking": False}
    assert "tools" not in request


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"summary":"missing fields"}',
    ],
)
@pytest.mark.asyncio
async def test_structured_generation_rejects_invalid_provider_output(content: str) -> None:
    model = BailianModel(
        model_settings(),
        client=FakeOpenAI(FakeCompletions(content=content)),
    )

    with pytest.raises(StructuredOutputError) as captured:
        await model.generate_structured("system", "user", MessageAssessment)

    assert captured.value.code == "structured_output_invalid"
    assert captured.value.status_code == 502
    assert content not in str(captured.value)


@pytest.mark.asyncio
async def test_text_generation_rejects_empty_provider_content() -> None:
    model = BailianModel(model_settings(), client=FakeOpenAI(FakeCompletions(content=None)))

    with pytest.raises(ModelProviderError):
        await model.generate_text("system", "user")


def provider_error(error_type: type[Exception], *, error_code: str | None = None) -> Exception:
    request = httpx2.Request("POST", "https://provider.invalid/chat/completions")
    if error_type is openai.APITimeoutError:
        return openai.APITimeoutError(request)
    if error_type is openai.APIConnectionError:
        return openai.APIConnectionError(request=request)
    status_codes = {
        openai.AuthenticationError: 401,
        openai.PermissionDeniedError: 403,
        openai.RateLimitError: 429,
        openai.BadRequestError: 400,
        openai.InternalServerError: 500,
    }
    response = httpx2.Response(status_codes[error_type], request=request)
    body = (
        {"code": error_code or "insufficient_quota"}
        if error_type is openai.PermissionDeniedError
        else None
    )
    return error_type("provider-sensitive-message", response=response, body=body)


@pytest.mark.parametrize(
    ("provider_exception", "public_exception", "code", "status_code"),
    [
        (
            provider_error(openai.AuthenticationError),
            ModelAuthenticationError,
            "provider_authentication_failed",
            502,
        ),
        (
            provider_error(openai.RateLimitError),
            ModelRateLimitError,
            "provider_rate_limited",
            503,
        ),
        (
            provider_error(openai.PermissionDeniedError),
            ModelRateLimitError,
            "provider_rate_limited",
            503,
        ),
        (
            provider_error(
                openai.PermissionDeniedError,
                error_code="AllocationQuota.FreeTierOnly",
            ),
            ModelRateLimitError,
            "provider_rate_limited",
            503,
        ),
        (
            provider_error(openai.APITimeoutError),
            ModelTimeoutError,
            "provider_timeout",
            504,
        ),
        (
            provider_error(openai.APIConnectionError),
            ModelUnavailableError,
            "provider_unavailable",
            503,
        ),
        (
            provider_error(openai.BadRequestError),
            ModelConfigurationError,
            "model_not_configured",
            503,
        ),
        (
            provider_error(openai.InternalServerError),
            ModelProviderError,
            "provider_error",
            502,
        ),
    ],
)
@pytest.mark.asyncio
async def test_provider_errors_are_mapped_without_leaking_details(
    provider_exception: Exception,
    public_exception: type[Exception],
    code: str,
    status_code: int,
) -> None:
    model = BailianModel(
        model_settings(),
        client=FakeOpenAI(FakeCompletions(error=provider_exception)),
    )

    with pytest.raises(public_exception) as captured:
        await model.generate_text("system", "user")

    assert captured.value.code == code
    assert captured.value.status_code == status_code
    assert "provider-sensitive-message" not in str(captured.value)


@pytest.mark.asyncio
async def test_model_closes_its_sdk_client() -> None:
    client = FakeOpenAI(FakeCompletions())
    model = BailianModel(model_settings(), client=client)

    await model.close()

    assert client.closed is True


@pytest.mark.asyncio
async def test_structured_validation_failure_is_logged_as_failed_operation(caplog) -> None:
    model = BailianModel(
        model_settings(),
        client=FakeOpenAI(FakeCompletions(content="not-json")),
    )

    with caplog.at_level(logging.INFO, logger="ecommerce_ai_agent.llm.client"):
        with pytest.raises(StructuredOutputError):
            await model.generate_structured("system", "user", MessageAssessment)

    record = next(
        record for record in caplog.records if record.message == "Model request completed"
    )
    assert record.provider == "bailian"
    assert record.model == "qwen3.8-27b"
    assert record.operation == "structured"
    assert record.outcome == "failure"
    assert record.error_type == "StructuredOutputError"
    assert isinstance(record.latency_ms, float)
