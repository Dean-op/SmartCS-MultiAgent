import logging
from decimal import Decimal
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
    def __init__(
        self,
        *,
        content: str | None = "ok",
        tool_calls: list[Any] | None = None,
        error: Exception | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.error = error
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any):
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        message = SimpleNamespace(content=self.content, tool_calls=self.tool_calls)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
            ),
        )


class FakeOpenAI:
    def __init__(self, completions: FakeCompletions, embeddings=None) -> None:
        self.chat = SimpleNamespace(completions=completions)
        self.embeddings = embeddings
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
async def test_text_generation_records_provider_token_usage_and_cost() -> None:
    from ecommerce_ai_agent.observability import observe_request

    completions = FakeCompletions(
        content="真实模型回复",
        prompt_tokens=100,
        completion_tokens=25,
    )
    model = BailianModel(model_settings(), client=FakeOpenAI(completions))

    with observe_request(
        "request-token-usage",
        input_price_per_million=3,
        output_price_per_million=12,
    ) as observation:
        await model.generate_text("system rules", "customer message")

    assert observation.model_calls == 1
    assert observation.input_tokens == 100
    assert observation.output_tokens == 25
    assert observation.estimated_cost_cny == Decimal("0.0006")


@pytest.mark.asyncio
async def test_tool_turn_returns_model_tool_calls_and_preserves_arguments() -> None:
    provider_tool_call = SimpleNamespace(
        id="call-order-1",
        function=SimpleNamespace(
            name="get_current_user_order",
            arguments='{"order_number":"EC2026080001"}',
        ),
    )
    completions = FakeCompletions(content=None, tool_calls=[provider_tool_call])
    model = BailianModel(model_settings(), client=FakeOpenAI(completions))
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_current_user_order",
                "description": "查询当前用户订单",
                "parameters": {
                    "type": "object",
                    "properties": {"order_number": {"type": "string"}},
                    "required": ["order_number"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    result = await model.generate_turn([{"role": "user", "content": "查一下 EC2026080001"}], tools)

    assert result.content is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call-order-1"
    assert result.tool_calls[0].name == "get_current_user_order"
    assert result.tool_calls[0].arguments == '{"order_number":"EC2026080001"}'
    request = completions.requests[0]
    assert request["tools"] == tools
    assert request["tool_choice"] == "auto"
    assert request["extra_body"] == {"enable_thinking": False}


@pytest.mark.asyncio
async def test_tool_turn_can_return_direct_answer_without_tool_call() -> None:
    model = BailianModel(
        model_settings(),
        client=FakeOpenAI(FakeCompletions(content="你好，有什么可以帮你？", tool_calls=[])),
    )

    result = await model.generate_turn(
        [{"role": "user", "content": "你好"}],
        [],
    )

    assert result.content == "你好，有什么可以帮你？"
    assert result.tool_calls == ()


@pytest.mark.asyncio
async def test_dense_embedding_uses_configured_model_and_dimensions(caplog) -> None:
    class FakeEmbeddings:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        async def create(self, **kwargs):
            self.requests.append(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=0, embedding=[0.1, 0.2]),
                    SimpleNamespace(index=1, embedding=[0.3, 0.4]),
                ]
            )

    embeddings = FakeEmbeddings()
    model = BailianModel(
        model_settings(
            embedding_model="text-embedding-v4",
            embedding_dimensions=1024,
        ),
        client=FakeOpenAI(FakeCompletions(), embeddings),
    )

    with caplog.at_level(logging.INFO, logger="ecommerce_ai_agent.llm.client"):
        vectors = await model.embed_texts(["退款政策", "配送政策"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert embeddings.requests == [
        {
            "model": "text-embedding-v4",
            "input": ["退款政策", "配送政策"],
            "dimensions": 1024,
            "encoding_format": "float",
        }
    ]
    record = next(record for record in caplog.records if record.operation == "embedding")
    assert record.model == "text-embedding-v4"


@pytest.mark.asyncio
async def test_text_embedding_v4_batches_at_ten_inputs() -> None:
    class BatchEmbeddings:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        async def create(self, **kwargs):
            batch_size = len(kwargs["input"])
            self.batch_sizes.append(batch_size)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=index, embedding=[float(index)])
                    for index in range(batch_size)
                ]
            )

    embeddings = BatchEmbeddings()
    model = BailianModel(
        model_settings(),
        client=FakeOpenAI(FakeCompletions(), embeddings),
    )

    vectors = await model.embed_texts([f"chunk-{index}" for index in range(11)])

    assert embeddings.batch_sizes == [10, 1]
    assert len(vectors) == 11


@pytest.mark.asyncio
async def test_text_rerank_calls_qwen3_compatible_endpoint_and_returns_scores() -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.91},
                    {"index": 0, "relevance_score": 0.63},
                ]
            }

    class FakeRerankClient:
        def __init__(self) -> None:
            self.requests: list[tuple[str, dict]] = []

        async def post(self, path: str, **kwargs):
            self.requests.append((path, kwargs))
            return FakeResponse()

        async def aclose(self) -> None:
            return None

    rerank_client = FakeRerankClient()
    model = BailianModel(
        model_settings(
            bailian_rerank_base_url="https://example.com/compatible-api/v1",
            rerank_model="qwen3-rerank",
        ),
        client=FakeOpenAI(FakeCompletions()),
        rerank_client=rerank_client,
    )

    results = await model.rerank_texts("退款期限", ["配送政策", "七天退款政策"], top_n=2)

    assert [(result.index, result.score) for result in results] == [(1, 0.91), (0, 0.63)]
    assert rerank_client.requests == [
        (
            "/reranks",
            {
                "headers": {"Authorization": "Bearer test-api-key"},
                "json": {
                    "model": "qwen3-rerank",
                    "query": "退款期限",
                    "documents": ["配送政策", "七天退款政策"],
                    "top_n": 2,
                },
            },
        )
    ]


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
async def test_failed_provider_attempt_is_counted_once() -> None:
    from ecommerce_ai_agent.observability import observe_request

    model = BailianModel(
        model_settings(),
        client=FakeOpenAI(FakeCompletions(error=provider_error(openai.AuthenticationError))),
    )

    with observe_request(
        "failed-model-call",
        input_price_per_million=3,
        output_price_per_million=12,
    ) as observation:
        with pytest.raises(ModelAuthenticationError):
            await model.generate_text("system", "user")

    assert observation.model_calls == 1
    assert observation.error_count == 1
    assert observation.error_types == ["ModelAuthenticationError"]


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
