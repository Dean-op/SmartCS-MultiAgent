import json
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any, TypeVar

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


class BailianModel:
    def __init__(self, settings: Settings, *, client: AsyncOpenAI | None = None) -> None:
        if (
            not settings.dashscope_api_key
            or not settings.bailian_base_url
            or not settings.llm_model
        ):
            raise ModelConfigurationError

        self._model = settings.llm_model
        self._temperature = settings.llm_temperature
        self._max_completion_tokens = settings.llm_max_completion_tokens
        self._embedding_model = settings.embedding_model
        self._embedding_dimensions = settings.embedding_dimensions
        self._client = client or AsyncOpenAI(
            api_key=settings.dashscope_api_key.get_secret_value(),
            base_url=str(settings.bailian_base_url),
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        started_at = perf_counter()
        try:
            completion = await self._complete(messages=self._messages(system_prompt, user_prompt))
            content = self._content(completion)
        except ModelError as exc:
            self._log("text", started_at, "failure", type(exc).__name__)
            raise
        self._log("text", started_at, "success")
        return content

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_type: type[SchemaT],
    ) -> SchemaT:
        started_at = perf_counter()
        try:
            schema_prompt = (
                f"{system_prompt}\n仅输出一个 JSON 对象，不要数组或额外文字。"
                f"JSON Schema: {json.dumps(schema_type.model_json_schema(), ensure_ascii=False)}"
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
        try:
            response = await self._client.embeddings.create(
                model=self._embedding_model,
                input=texts,
                dimensions=self._embedding_dimensions,
                encoding_format="float",
            )
            vectors = [
                item.embedding for item in sorted(response.data, key=lambda item: item.index)
            ]
            if len(vectors) != len(texts):
                raise ModelProviderError
        except openai.APIError as exc:
            error = self._map_error(exc)
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

    async def close(self) -> None:
        await self._client.close()

    async def _complete(self, **request: Any) -> Any:
        try:
            return await self._client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                max_completion_tokens=self._max_completion_tokens,
                **request,
            )
        except openai.APIError as exc:
            raise self._map_error(exc) from exc

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
            raise ModelProviderError from exc
        if not isinstance(content, str) or not content.strip():
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
            raise ModelProviderError from exc

        content = message.content.strip() if isinstance(message.content, str) else None
        if not content and not tool_calls:
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
