import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from functools import partial
from typing import Literal, TypedDict

import asyncpg
import httpx
from redis.asyncio import Redis

from ecommerce_ai_agent.config import Settings

Probe = Callable[[], Awaitable[None]]
DependencyStatus = Literal["ok", "unavailable"]


class HealthReport(TypedDict):
    status: Literal["ready", "not_ready"]
    dependencies: dict[str, DependencyStatus]


logger = logging.getLogger(__name__)


async def check_postgres(settings: Settings) -> None:
    connection = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        timeout=settings.healthcheck_timeout_seconds,
    )
    try:
        result = await connection.fetchval("SELECT 1")
        if result != 1:
            raise RuntimeError("PostgreSQL readiness query returned an unexpected result")
    finally:
        await connection.close()


async def check_redis(settings: Settings) -> None:
    client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=settings.healthcheck_timeout_seconds,
        socket_timeout=settings.healthcheck_timeout_seconds,
        decode_responses=True,
    )
    try:
        if not await client.ping():
            raise RuntimeError("Redis readiness ping returned an unexpected result")
    finally:
        await client.aclose()


async def check_milvus(settings: Settings) -> None:
    url = f"http://{settings.milvus_host}:{settings.milvus_management_port}/healthz"
    async with httpx.AsyncClient(timeout=settings.healthcheck_timeout_seconds) as client:
        response = await client.get(url)
        response.raise_for_status()


def build_health_checker(settings: Settings) -> "HealthChecker":
    return HealthChecker(
        {
            "postgres": partial(check_postgres, settings),
            "redis": partial(check_redis, settings),
            "milvus": partial(check_milvus, settings),
        }
    )


class HealthChecker:
    def __init__(self, probes: Mapping[str, Probe]) -> None:
        self._probes = probes

    async def check(self) -> HealthReport:
        names = list(self._probes)
        statuses = await asyncio.gather(
            *(self._check_dependency(name, self._probes[name]) for name in names)
        )
        dependencies = dict(zip(names, statuses, strict=True))
        overall_status = "ready" if all(status == "ok" for status in statuses) else "not_ready"
        return {"status": overall_status, "dependencies": dependencies}

    async def _check_dependency(self, name: str, probe: Probe) -> DependencyStatus:
        try:
            await probe()
        except Exception as exc:  # noqa: BLE001 - health checks must degrade to a status
            logger.warning(
                "Dependency health check failed",
                extra={"dependency": name, "error_type": type(exc).__name__},
            )
            return "unavailable"
        return "ok"
