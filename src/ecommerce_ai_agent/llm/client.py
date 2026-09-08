import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, TypeVar

import httpx
import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.llm.errors import (
    ModelAuthenticationError,
    ModelConfigurationError,
    ModelError,
    ModelProviderError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredOutputError,
)
from ecommerce_ai_agent.observability import (
    operation_span,
    record_completion_usage,
    record_error,
    record_model_call,
)

SchemaT = TypeVar("SchemaT", bound=BaseModel)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ModelTurn:
    content: str | None
    tool_calls: tuple[ToolCall, ...]


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


@dataclass(frozen=True)
class StreamedText:
    content: str
    reasoning_content: str


class BailianModel:
    def __init__(
        self,
        settings: Settings,
        *,
        client: AsyncOpenAI | None = None,
        rerank_client: httpx.AsyncClient | Any | None = None,
    ) -> None:
        if (
            not settings.dashscope_api_key
            or not settings.bailian_base_url
            or not settings.llm_model
        ):
            raise ModelConfigurationError

        self._api_key = settings.dashscope_api_key.get_secret_value()
        self._model = settings.llm_model
        self._temperature = settings.llm_temperature
        self._max_completion_tokens = settings.llm_max_completion_tokens
        self._embedding_model = settings.embedding_model
        self._embedding_dimensions = settings.embedding_dimensions
        self._rerank_model = settings.rerank_model
        self._rerank_client = rerank_client
        if self._rerank_client is None and settings.bailian_rerank_base_url:
            self._rerank_client = httpx.AsyncClient(
                base_url=str(settings.bailian_rerank_base_url),
                timeout=settings.llm_timeout_seconds,
            )
        self._client = client or AsyncOpenAI(
            api_key=self._api_key,
            base_url=str(settings.bailian_base_url),
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        started_at = perf_counter()
        with operation_span("model.text", provider="bailian", model=self._model):
            try:
                completion = await self._complete(
                    messages=self._messages(system_prompt, user_prompt)
                )
                content = self._content(completion)
            except ModelError as exc:
                self._log("text", started_at, "failure", type(exc).__name__)
                raise
        self._log("text", started_at, "success")
        return content

    async def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        emit: Callable[[str, str], None],
    ) -> StreamedText:
        return await self.stream_messages(self._messages(system_prompt, user_prompt), emit)

    async def stream_messages(
        self,
        messages: list[dict[str, Any]],
        emit: Callable[[str, str], None],
    ) -> StreamedText:
        started_at = perf_counter()
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        input_tokens = output_tokens = 0
        with operation_span("model.stream", provider="bailian", model=self._model):
            try:
                stream = await self._client.chat.completions.create(
                    model=self._model,
                    temperature=self._temperature,
                    max_completion_tokens=self._max_completion_tokens,
                    messages=messages,
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body={"enable_thinking": True},
                )
                async for chunk in stream:
                    usage_input, usage_output = record_completion_usage(chunk)
                    input_tokens = usage_input or input_tokens
                    output_tokens = usage_output or output_tokens
                    if not getattr(chunk, "choices", None):
                        continue
                    delta = chunk.choices[0].delta
                    reasoning = getattr(delta, "reasoning_content", None)
                    content = getattr(delta, "content", None)
                    if reasoning:
                        reasoning_parts.append(reasoning)
                        emit("reasoning_delta", reasoning)
                    if content:
                        content_parts.append(content)
                        emit("delta", content)
            except openai.APIError as exc:
                error = self._map_error(exc)
                record_model_call(error_type=type(error).__name__)
                self._log("stream", started_at, "failure", type(error).__name__)
                raise error from exc
            except (AttributeError, TypeError) as exc:
                record_model_call(error_type="ModelProviderError")
                self._log("stream", started_at, "failure", "ModelProviderError")
                raise ModelProviderError from exc
        content = "".join(content_parts).strip()
        if not content:
            record_model_call(error_type="ModelProviderError")
            raise ModelProviderError
        record_model_call(input_tokens=input_tokens, output_tokens=output_tokens)
        self._log("stream", started_at, "success")
        return StreamedText(content=content, reasoning_content="".join(reasoning_parts).strip())

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_type: type[SchemaT],
    ) -> SchemaT:
        started_at = perf_counter()
        with operation_span("model.structured", provider="bailian", model=self._model):
            try:
                schema_prompt = (
                    f"{system_prompt}\n仅输出一个 JSON 对象，不要数组或额外文字。"
                    "JSON Schema: "
                    f"{json.dumps(schema_type.model_json_schema(), ensure_ascii=False)}"
                )
                completion = await self._complete(
                    messages=self._messages(schema_prompt, user_prompt),
                    response_format={"type": "json_object"},
                    extra_body={"enable_thinking": False},
                )
                content = self._content(completion)
                result = schema_type.model_validate(json.loads(content))
            except (json.JSONDecodeError, TypeError, ValidationError) as exc:
                error = StructuredOutputError()
                record_error(type(error).__name__)
                self._log("structured", started_at, "failure", type(error).__name__)
                raise error from exc
            except ModelError as exc:
                self._log("structured", started_at, "failure", type(exc).__name__)
                raise
        self._log("structured", started_at, "success")
        return result

    async def generate_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        started_at = perf_counter()
        with operation_span("model.tools", provider="bailian", model=self._model):
            try:
                completion = await self._complete(
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    extra_body={"enable_thinking": False},
                )
                turn = self._turn(completion)
            except ModelError as exc:
                self._log("tools", started_at, "failure", type(exc).__name__)
                raise
        self._log("tools", started_at, "success")
        return turn

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        started_at = perf_counter()
        with operation_span("model.embedding", provider="bailian", model=self._embedding_model):
            try:
                vectors: list[list[float]] = []
                for start in range(0, len(texts), 10):
                    batch = texts[start : start + 10]
                    response = await self._client.embeddings.create(
                        model=self._embedding_model,
                        input=batch,
                        dimensions=self._embedding_dimensions,
                        encoding_format="float",
                    )
                    input_tokens, output_tokens = record_completion_usage(response)
                    record_model_call(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    batch_vectors = [
                        item.embedding
                        for item in sorted(response.data, key=lambda item: item.index)
                    ]
                    if len(batch_vectors) != len(batch):
                        raise ModelProviderError
                    vectors.extend(batch_vectors)
            except openai.APIError as exc:
                error = self._map_error(exc)
                record_model_call(error_type=type(error).__name__)
                self._log(
                    "embedding",
                    started_at,
                    "failure",
                    type(error).__name__,
                    self._embedding_model,
                )
                raise error from exc
            except (AttributeError, TypeError) as exc:
                error = ModelProviderError()
                record_error(type(error).__name__)
                self._log(
                    "embedding",
                    started_at,
                    "failure",
                    type(error).__name__,
                    self._embedding_model,
                )
                raise error from exc
        self._log("embedding", started_at, "success", model_name=self._embedding_model)
        return vectors

    async def rerank_texts(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int,
    ) -> list[RerankResult]:
        if not documents:
            return []
        if self._rerank_client is None:
            raise ModelConfigurationError
        started_at = perf_counter()
        with operation_span("model.rerank", provider="bailian", model=self._rerank_model):
            try:
                response = await self._rerank_client.post(
                    "/reranks",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._rerank_model,
                        "query": query,
                        "documents": documents,
                        "top_n": min(top_n, len(documents)),
                    },
                )
                response.raise_for_status()
                record_model_call()
                results = [
                    RerankResult(index=int(item["index"]), score=float(item["relevance_score"]))
                    for item in response.json()["results"]
                ]
            except httpx.TimeoutException as exc:
                error: ModelError = ModelTimeoutError()
                record_model_call(error_type=type(error).__name__)
                self._log("rerank", started_at, "failure", type(error).__name__, self._rerank_model)
                raise error from exc
            except httpx.RequestError as exc:
                error = ModelUnavailableError()
                record_model_call(error_type=type(error).__name__)
                self._log("rerank", started_at, "failure", type(error).__name__, self._rerank_model)
                raise error from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    error = ModelAuthenticationError()
                elif exc.response.status_code == 429:
                    error = ModelRateLimitError()
                elif exc.response.status_code in (400, 404, 422):
                    error = ModelConfigurationError()
                else:
                    error = ModelProviderError()
                record_model_call(error_type=type(error).__name__)
                self._log("rerank", started_at, "failure", type(error).__name__, self._rerank_model)
                raise error from exc
            except (KeyError, TypeError, ValueError) as exc:
                error = ModelProviderError()
                record_error(type(error).__name__)
                self._log("rerank", started_at, "failure", type(error).__name__, self._rerank_model)
                raise error from exc
        self._log("rerank", started_at, "success", model_name=self._rerank_model)
        return results

    async def close(self) -> None:
        if self._rerank_client is not None:
            await self._rerank_client.aclose()
        await self._client.close()

    async def _complete(self, **request: Any) -> Any:
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                max_completion_tokens=self._max_completion_tokens,
                **request,
            )
        except openai.APIError as exc:
            error = self._map_error(exc)
            record_model_call(error_type=type(error).__name__)
            raise error from exc
        input_tokens, output_tokens = record_completion_usage(completion)
        record_model_call(input_tokens=input_tokens, output_tokens=output_tokens)
        return completion

    def _log(
        self,
        operation: str,
        started_at: float,
        outcome: str,
        error_type: str | None = None,
        model_name: str | None = None,
    ) -> None:
        extra = {
            "provider": "bailian",
            "model": model_name or self._model,
            "operation": operation,
            "latency_ms": round((perf_counter() - started_at) * 1000, 2),
            "outcome": outcome,
        }
        if error_type:
            extra["error_type"] = error_type
        logger.info("Model request completed", extra=extra)

    @staticmethod
    def _messages(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _content(completion: Any) -> str:
        try:
            content = completion.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            record_error("ModelProviderError")
            raise ModelProviderError from exc
        if not isinstance(content, str) or not content.strip():
            record_error("ModelProviderError")
            raise ModelProviderError
        return content.strip()

    @staticmethod
    def _turn(completion: Any) -> ModelTurn:
        try:
            message = completion.choices[0].message
            provider_calls = message.tool_calls or []
            tool_calls = tuple(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=call.function.arguments,
                )
                for call in provider_calls
            )
        except (AttributeError, IndexError, TypeError) as exc:
            record_error("ModelProviderError")
            raise ModelProviderError from exc

        content = message.content.strip() if isinstance(message.content, str) else None
        if not content and not tool_calls:
            record_error("ModelProviderError")
            raise ModelProviderError
        return ModelTurn(content=content, tool_calls=tool_calls)

    @staticmethod
    def _map_error(exception: openai.APIError) -> ModelError:
        if isinstance(exception, openai.PermissionDeniedError) and exception.code in {
            "insufficient_quota",
            "AllocationQuota.FreeTierOnly",
        }:
            return ModelRateLimitError()
        if isinstance(exception, openai.AuthenticationError | openai.PermissionDeniedError):
            return ModelAuthenticationError()
        if isinstance(exception, openai.RateLimitError):
            return ModelRateLimitError()
        if isinstance(exception, openai.APITimeoutError):
            return ModelTimeoutError()
        if isinstance(exception, openai.APIConnectionError):
            return ModelUnavailableError()
        if isinstance(
            exception,
            openai.BadRequestError | openai.NotFoundError | openai.UnprocessableEntityError,
        ):
            return ModelConfigurationError()
        return ModelProviderError()
