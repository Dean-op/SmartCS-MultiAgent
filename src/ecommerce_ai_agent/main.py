import logging

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.health import HealthChecker, build_health_checker
from ecommerce_ai_agent.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    health_checker: HealthChecker | None = None,
) -> FastAPI:
    settings = settings or Settings()
    health_checker = health_checker or build_health_checker(settings)
    configure_logging(settings.log_level)
    logger.info(
        "Application configured",
        extra={"environment": settings.app_env},
    )
    application = FastAPI(title=settings.app_name)

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
