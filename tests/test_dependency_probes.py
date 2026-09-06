from typing import Any

import pytest
from pydantic import SecretStr

from ecommerce_ai_agent import health
from ecommerce_ai_agent.config import Settings


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        postgres_host="postgres",
        redis_host="redis",
        milvus_host="milvus",
        postgres_password=SecretStr("test-password"),
    )


@pytest.mark.asyncio
async def test_postgres_probe_executes_select_and_closes_connection(monkeypatch) -> None:
    events: list[Any] = []

    class FakeConnection:
        async def fetchval(self, query: str) -> int:
            events.append(("query", query))
            return 1

        async def close(self) -> None:
            events.append(("close",))

    async def fake_connect(**kwargs: Any) -> FakeConnection:
        events.append(("connect", kwargs))
        return FakeConnection()

    monkeypatch.setattr(health.asyncpg, "connect", fake_connect)

    await health.check_postgres(build_settings())

    assert events[0][0] == "connect"
    assert events[0][1]["host"] == "postgres"
    assert events[0][1]["password"] == "test-password"
    assert events[1:] == [("query", "SELECT 1"), ("close",)]


@pytest.mark.asyncio
async def test_redis_probe_pings_and_closes_client(monkeypatch) -> None:
    events: list[Any] = []

    class FakeRedis:
        async def ping(self) -> bool:
            events.append(("ping",))
            return True

        async def aclose(self) -> None:
            events.append(("close",))

    def fake_redis(**kwargs: Any) -> FakeRedis:
        events.append(("connect", kwargs))
        return FakeRedis()

    monkeypatch.setattr(health, "Redis", fake_redis)

    await health.check_redis(build_settings())

    assert events[0][0] == "connect"
    assert events[0][1]["host"] == "redis"
    assert events[1:] == [("ping",), ("close",)]


@pytest.mark.asyncio
async def test_milvus_probe_uses_management_health_endpoint(monkeypatch) -> None:
    events: list[Any] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            events.append(("raise_for_status",))

    class FakeClient:
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            events.append(("get", url))
            return FakeResponse()

    def fake_client(**kwargs: Any) -> FakeClient:
        events.append(("client", kwargs))
        return FakeClient()

    monkeypatch.setattr(health.httpx, "AsyncClient", fake_client)

    await health.check_milvus(build_settings())

    assert events[0][0] == "client"
    assert events[1:] == [
        ("get", "http://milvus:9091/healthz"),
        ("raise_for_status",),
    ]


@pytest.mark.asyncio
async def test_default_health_checker_contains_all_runtime_dependencies(monkeypatch) -> None:
    async def healthy(_: Settings) -> None:
        return None

    monkeypatch.setattr(health, "check_postgres", healthy)
    monkeypatch.setattr(health, "check_redis", healthy)
    monkeypatch.setattr(health, "check_milvus", healthy)

    report = await health.build_health_checker(build_settings()).check()

    assert report["dependencies"] == {
        "postgres": "ok",
        "redis": "ok",
        "milvus": "ok",
    }
