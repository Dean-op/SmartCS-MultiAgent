import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("ecommerce_ai_agent")
_current_observation: ContextVar["RequestObservation | None"] = ContextVar(
    "request_observation",
    default=None,
)
_tracing_configured = False


@dataclass
class RequestObservation:
    request_id: str
    input_price_per_million: Decimal
    output_price_per_million: Decimal
    started_at: float = field(default_factory=perf_counter)
    path: list[str] = field(default_factory=list)
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error_count: int = 0
    error_types: list[str] = field(default_factory=list)
    http_method: str | None = None
    http_path: str | None = None
    http_status_code: int | None = None
    trace_id: str | None = None
    span_id: str | None = None

    @property
    def estimated_cost_cny(self) -> Decimal:
        return (
            Decimal(self.input_tokens) * self.input_price_per_million
            + Decimal(self.output_tokens) * self.output_price_per_million
        ) / Decimal(1_000_000)


def configure_tracing(service_name: str, *, console_exporter: bool) -> None:
    global _tracing_configured
    if _tracing_configured:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if console_exporter:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _tracing_configured = True


@contextmanager
def observe_request(
    request_id: str,
    *,
    input_price_per_million: Decimal | int | float,
    output_price_per_million: Decimal | int | float,
) -> Iterator[RequestObservation]:
    observation = RequestObservation(
        request_id=request_id,
        input_price_per_million=Decimal(str(input_price_per_million)),
        output_price_per_million=Decimal(str(output_price_per_million)),
    )
    token = _current_observation.set(observation)
    try:
        yield observation
    except Exception as exc:
        record_error(type(exc).__name__)
        raise
    finally:
        logger.info(
            "Request completed",
            extra={
                "request_id": observation.request_id,
                "execution_path": " -> ".join(observation.path),
                "latency_ms": round((perf_counter() - observation.started_at) * 1000, 2),
                "model_calls": observation.model_calls,
                "tool_calls": observation.tool_calls,
                "input_tokens": observation.input_tokens,
                "output_tokens": observation.output_tokens,
                "estimated_cost_cny": float(observation.estimated_cost_cny),
                "error_count": observation.error_count,
                "error_types": observation.error_types,
                "http_method": observation.http_method,
                "http_path": observation.http_path,
                "http_status_code": observation.http_status_code,
                "trace_id": observation.trace_id,
                "span_id": observation.span_id,
            },
        )
        _current_observation.reset(token)


def record_path(component: str) -> None:
    observation = _current_observation.get()
    if observation is not None:
        observation.path.append(component)


def record_model_call(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error_type: str | None = None,
) -> None:
    observation = _current_observation.get()
    if observation is None:
        return
    observation.model_calls += 1
    observation.input_tokens += input_tokens
    observation.output_tokens += output_tokens
    if error_type:
        observation.error_count += 1
        observation.error_types.append(error_type)


def record_tool_call(name: str) -> None:
    observation = _current_observation.get()
    if observation is not None:
        observation.tool_calls += 1
        observation.path.append(f"tool:{name}")


def record_error(error_type: str) -> None:
    observation = _current_observation.get()
    if observation is not None:
        observation.error_count += 1
        observation.error_types.append(error_type)


def record_completion_usage(completion: Any) -> tuple[int, int]:
    usage = getattr(completion, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    return input_tokens, output_tokens


@contextmanager
def operation_span(name: str, **attributes: str | int | float | bool) -> Iterator[None]:
    with tracer.start_as_current_span(name, attributes=attributes):
        yield


def trace_ids() -> tuple[str | None, str | None]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None, None
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"


def current_request_trace() -> tuple[str | None, str | None]:
    observation = _current_observation.get()
    if observation is None:
        return None, None
    return observation.request_id, observation.trace_id


class RequestObservabilityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        input_price_per_million: Decimal,
        output_price_per_million: Decimal,
    ) -> None:
        self.app = app
        self.input_price = input_price_per_million
        self.output_price = output_price_per_million

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied_id = headers.get(b"x-request-id", b"").decode(errors="ignore")
        request_id = (
            supplied_id if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", supplied_id) else str(uuid4())
        )
        with observe_request(
            request_id,
            input_price_per_million=self.input_price,
            output_price_per_million=self.output_price,
        ) as observation:
            observation.http_method = scope["method"]
            observation.http_path = scope["path"]
            with operation_span(
                "http.request",
                **{
                    "http.request.method": scope["method"],
                    "url.path": scope["path"],
                },
            ):
                observation.trace_id, observation.span_id = trace_ids()

                async def send_observed(message: Message) -> None:
                    if message["type"] == "http.response.start":
                        observation.http_status_code = message["status"]
                        if message["status"] >= 400:
                            record_error(f"HTTP{message['status']}")
                        response_headers = list(message.get("headers", []))
                        response_headers.append((b"x-request-id", request_id.encode()))
                        if observation.trace_id and observation.span_id:
                            traceparent = f"00-{observation.trace_id}-{observation.span_id}-01"
                            response_headers.append((b"traceparent", traceparent.encode()))
                        message["headers"] = response_headers
                    await send(message)

                await self.app(scope, receive, send_observed)
