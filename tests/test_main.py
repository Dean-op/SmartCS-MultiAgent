import logging
import re
from collections.abc import Awaitable, Callable

import httpx
import pytest
from pydantic import SecretStr

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.health import HealthChecker
from ecommerce_ai_agent.main import create_app

Probe = Callable[[], Awaitable[None]]


async def healthy_probe() -> None:
    return None


async def failing_probe() -> None:
    raise ConnectionError


def build_app(*, redis_probe: Probe = healthy_probe):  # type annotation follows production API
    settings = Settings(_env_file=None, postgres_password=SecretStr("test-password"))
    checker = HealthChecker(
        {
            "postgres": healthy_probe,
            "redis": redis_probe,
            "milvus": healthy_probe,
        }
    )
    return create_app(settings=settings, health_checker=checker)


@pytest.mark.asyncio
async def test_liveness_reports_api_process_is_alive() -> None:
    transport = httpx.ASGITransport(app=build_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_request_trace_returns_correlation_headers_and_summary(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="ecommerce_ai_agent.observability"):
        transport = httpx.ASGITransport(app=build_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/health/live",
                headers={"x-request-id": "demo-request-1"},
            )

    assert response.headers["x-request-id"] == "demo-request-1"
    assert re.fullmatch(
        r"00-[0-9a-f]{32}-[0-9a-f]{16}-01",
        response.headers["traceparent"],
    )
    record = next(record for record in caplog.records if record.message == "Request completed")
    assert record.request_id == "demo-request-1"
    assert record.http_method == "GET"
    assert record.http_path == "/health/live"
    assert record.http_status_code == 200
    assert record.trace_id == response.headers["traceparent"].split("-")[1]
    assert record.error_count == 0


@pytest.mark.asyncio
async def test_failed_http_response_is_counted_without_leaking_details(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="ecommerce_ai_agent.observability"):
        transport = httpx.ASGITransport(app=build_app(redis_probe=failing_probe))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/ready")

    assert response.status_code == 503
    record = next(record for record in caplog.records if record.message == "Request completed")
    assert record.error_count == 1
    assert record.error_types == ["HTTP503"]


@pytest.mark.asyncio
async def test_readiness_returns_ok_when_all_dependencies_are_available() -> None:
    transport = httpx.ASGITransport(app=build_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_readiness_returns_service_unavailable_when_a_dependency_fails() -> None:
    transport = httpx.ASGITransport(app=build_app(redis_probe=failing_probe))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {
            "postgres": "ok",
            "redis": "unavailable",
            "milvus": "ok",
        },
    }


def test_application_factory_can_build_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")

    application = create_app()

    assert application.title == "ecommerce-ai-agent"
