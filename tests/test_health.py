from collections.abc import Awaitable, Callable

import pytest

from ecommerce_ai_agent.health import HealthChecker

Probe = Callable[[], Awaitable[None]]


async def healthy_probe() -> None:
    return None


async def failing_probe() -> None:
    raise ConnectionError("contains-sensitive-connection-details")


@pytest.mark.asyncio
async def test_health_checker_is_ready_when_all_dependencies_respond() -> None:
    probes: dict[str, Probe] = {
        "postgres": healthy_probe,
        "redis": healthy_probe,
        "milvus": healthy_probe,
    }

    report = await HealthChecker(probes).check()

    assert report == {
        "status": "ready",
        "dependencies": {
            "postgres": "ok",
            "redis": "ok",
            "milvus": "ok",
        },
    }


@pytest.mark.asyncio
async def test_health_checker_is_not_ready_without_leaking_dependency_errors() -> None:
    probes: dict[str, Probe] = {
        "postgres": healthy_probe,
        "redis": failing_probe,
        "milvus": healthy_probe,
    }

    report = await HealthChecker(probes).check()

    assert report == {
        "status": "not_ready",
        "dependencies": {
            "postgres": "ok",
            "redis": "unavailable",
            "milvus": "ok",
        },
    }
    assert "contains-sensitive-connection-details" not in repr(report)
