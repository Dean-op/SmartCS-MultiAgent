import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.database import (
    build_checkpoint_url,
    build_database_url,
    create_database,
)


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        postgres_host="db.internal",
        postgres_port=5544,
        postgres_db="business",
        postgres_user="service_user",
        postgres_password=SecretStr("p@ss:/#word"),
    )


def test_database_url_preserves_components_and_hides_password() -> None:
    url = build_database_url(build_settings())

    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "db.internal"
    assert url.port == 5544
    assert url.database == "business"
    assert url.username == "service_user"
    assert url.password == "p@ss:/#word"
    assert "p@ss:/#word" not in str(url)


def test_checkpoint_url_uses_psycopg_compatible_postgresql_scheme() -> None:
    url = build_checkpoint_url(build_settings())

    assert url.drivername == "postgresql"
    assert url.password == "p@ss:/#word"
    assert url.render_as_string(hide_password=False).startswith("postgresql://")


@pytest.mark.asyncio
async def test_database_creates_independent_non_expiring_async_sessions() -> None:
    database = create_database(build_settings())

    first = database.session_factory()
    second = database.session_factory()
    try:
        assert isinstance(first, AsyncSession)
        assert first is not second
        assert first.sync_session.expire_on_commit is False
    finally:
        await first.close()
        await second.close()
        await database.engine.dispose()
