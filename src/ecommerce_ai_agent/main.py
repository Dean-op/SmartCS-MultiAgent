import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
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
    RequestObservabilityMiddleware,
    configure_tracing,
)
from ecommerce_ai_agent.safety import SafetyService
from ecommerce_ai_agent.services.chat import ChatService

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    health_checker: HealthChecker | None = None,
    chat_service: ChatService | None = None,
    frontend_directory: Path | None = None,
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
            knowledge = KnowledgeBase(settings, model)
            safety = SafetyService(
                model,
                semantic_review_threshold=settings.safety_semantic_review_threshold,
                semantic_block_threshold=settings.safety_semantic_block_threshold,
            )
            service = ChatService(
                model,
                BusinessTools(database.session_factory, settings),
                knowledge,
                checkpointer=checkpointer,
            )
            application.state.chat_service = service
            application.state.database = database
            application.state.knowledge_base = knowledge
            application.state.safety_service = safety
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
    description = "M17 safety, PII and PDF API for the e-commerce Multi-Agent project."
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=description,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "health", "description": "Application and dependency health"},
            {"name": "auth", "description": "Development login and JWT access token"},
            {"name": "chat", "description": "Versioned chat API"},
            {"name": "conversations", "description": "Owned conversation history"},
            {"name": "knowledge", "description": "Admin knowledge management"},
            {"name": "reviews", "description": "Admin refund review API"},
        ],
    )
    application.state.chat_service = chat_service
    application.state.database = None
    application.state.knowledge_base = None
    application.state.safety_service = None
    application.state.knowledge_rebuild_lock = asyncio.Lock()
    application.state.settings = settings
    register_exception_handlers(application)
    application.include_router(api_v1_router)
    application.add_middleware(
        RequestObservabilityMiddleware,
        input_price_per_million=settings.llm_input_price_per_million_cny,
        output_price_per_million=settings.llm_output_price_per_million_cny,
    )

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

    frontend_directory = frontend_directory or (
        Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )
    if (frontend_directory / "index.html").exists():
        assets = frontend_directory / "assets"
        if assets.exists():
            application.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

        @application.get("/", include_in_schema=False)
        async def frontend() -> FileResponse:
            return FileResponse(frontend_directory / "index.html")

    return application
