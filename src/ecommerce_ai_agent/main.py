import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from ecommerce_ai_agent.api.errors import register_exception_handlers
from ecommerce_ai_agent.api.v1.router import router as api_v1_router
from ecommerce_ai_agent.business_tools import BusinessTools
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.database import build_checkpoint_url, create_database
from ecommerce_ai_agent.health import HealthChecker, build_health_checker
from ecommerce_ai_agent.knowledge import KnowledgeBase
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.llm.errors import ModelConfigurationError
from ecommerce_ai_agent.logging import configure_logging
from ecommerce_ai_agent.observability import (
    configure_tracing,
    observe_request,
    operation_span,
    record_error,
    trace_ids,
)
from ecommerce_ai_agent.services.chat import ChatService

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    health_checker: HealthChecker | None = None,
    chat_service: ChatService | None = None,
) -> FastAPI:
    settings = settings or Settings()
    health_checker = health_checker or build_health_checker(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if chat_service is not None:
            try:
                yield
            finally:
                await chat_service.close()
            return

        try:
            model = BailianModel(settings)
        except ModelConfigurationError:
            yield
            return

        database = create_database(settings)
        checkpoint_dsn = build_checkpoint_url(settings).render_as_string(hide_password=False)
        async with AsyncPostgresSaver.from_conn_string(checkpoint_dsn) as checkpointer:
            await checkpointer.setup()
            service = ChatService(
                model,
                BusinessTools(database.session_factory, settings),
                KnowledgeBase(settings, model),
                checkpointer=checkpointer,
            )
            application.state.chat_service = service
            application.state.database = database
            try:
                yield
            finally:
                await service.close()
                await database.engine.dispose()

    configure_logging(settings.log_level)
    configure_tracing(settings.app_name, console_exporter=settings.otel_console_exporter)
    logger.info(
        "Application configured",
        extra={"environment": settings.app_env},
    )
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="M10 persistent conversation API for the e-commerce AI Agent system.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "health", "description": "Application and dependency health"},
            {"name": "chat", "description": "Versioned chat API"},
            {"name": "reviews", "description": "Admin refund review API"},
        ],
    )
    application.state.chat_service = chat_service
    application.state.database = None
    application.state.settings = settings
    register_exception_handlers(application)
    application.include_router(api_v1_router)

    @application.middleware("http")
    async def request_observability(request: Request, call_next):
        supplied_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_id if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", supplied_id) else str(uuid4())
        )
        with observe_request(
            request_id,
            input_price_per_million=settings.llm_input_price_per_million_cny,
            output_price_per_million=settings.llm_output_price_per_million_cny,
        ) as observation:
            observation.http_method = request.method
            observation.http_path = request.url.path
            with operation_span(
                "http.request",
                **{
                    "http.request.method": request.method,
                    "url.path": request.url.path,
                },
            ):
                observation.trace_id, observation.span_id = trace_ids()
                response = await call_next(request)
                observation.http_status_code = response.status_code
                if response.status_code >= 400:
                    record_error(f"HTTP{response.status_code}")
                response.headers["x-request-id"] = request_id
                if observation.trace_id and observation.span_id:
                    response.headers["traceparent"] = (
                        f"00-{observation.trace_id}-{observation.span_id}-01"
                    )
                return response

    @application.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @application.get("/health/ready", tags=["health"])
    async def readiness() -> JSONResponse:
        report = await health_checker.check()
        status_code = (
            status.HTTP_200_OK
            if report["status"] == "ready"
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        return JSONResponse(status_code=status_code, content=report)

    return application
