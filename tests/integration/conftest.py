from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import asyncpg
import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.database import Database, build_database_url
from ecommerce_ai_agent.seed import seed_database

TEST_DATABASE_NAME = "ecommerce_agent_test"
EXPECTED_TABLES = {
    "users",
    "products",
    "orders",
    "order_items",
    "shipments",
    "refunds",
    "human_reviews",
    "conversations",
    "conversation_messages",
    "knowledge_documents",
}
EXPECTED_ENUMS = {
    "user_role",
    "order_status",
    "payment_status",
    "shipment_status",
    "refund_status",
    "review_status",
    "review_priority",
    "conversation_message_role",
    "conversation_message_status",
}


def pytest_asyncio_loop_factories(config, item):
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


@dataclass(frozen=True, slots=True)
class MigrationSnapshots:
    upgraded_tables: set[str]
    upgraded_enums: set[str]
    downgraded_tables: set[str]
    downgraded_enums: set[str]


@dataclass(frozen=True, slots=True)
class IntegrationDatabase:
    database: Database
    migrations: MigrationSnapshots

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self.database.session_factory


def assert_safe_test_database_name(name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*_test", name):
        raise RuntimeError(f"Refusing to manage unsafe test database name: {name!r}")


async def database_objects(settings: Settings) -> tuple[set[str], set[str]]:
    connection = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
    )
    try:
        tables = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        enums = await connection.fetch(
            """
            SELECT t.typname
            FROM pg_type AS t
            JOIN pg_namespace AS n ON n.oid = t.typnamespace
            WHERE n.nspname = 'public' AND t.typtype = 'e'
            """
        )
        return (
            {row["tablename"] for row in tables} & EXPECTED_TABLES,
            {row["typname"] for row in enums} & EXPECTED_ENUMS,
        )
    finally:
        await connection.close()


async def run_alembic(
    settings: Settings,
    operation: Callable[[Config, str], None],
    revision: str,
) -> None:
    configuration = Config("alembic.ini")
    configuration.attributes["database_url"] = build_database_url(settings).render_as_string(
        hide_password=False
    )
    await asyncio.to_thread(operation, configuration, revision)


@pytest_asyncio.fixture(scope="session")
async def test_database() -> AsyncIterator[IntegrationDatabase]:
    assert_safe_test_database_name(TEST_DATABASE_NAME)
    base_settings = Settings()
    try:
        admin = await asyncpg.connect(
            host=base_settings.postgres_host,
            port=base_settings.postgres_port,
            database="postgres",
            user=base_settings.postgres_user,
            password=base_settings.postgres_password.get_secret_value(),
        )
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.fail(f"PostgreSQL integration database is unavailable: {type(exc).__name__}")

    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{TEST_DATABASE_NAME}"')
    finally:
        await admin.close()

    settings = base_settings.model_copy(update={"postgres_db": TEST_DATABASE_NAME})
    database: Database | None = None
    try:
        await run_alembic(settings, command.upgrade, "head")
        upgraded_tables, upgraded_enums = await database_objects(settings)
        await run_alembic(settings, command.downgrade, "base")
        downgraded_tables, downgraded_enums = await database_objects(settings)
        await run_alembic(settings, command.upgrade, "head")

        engine = create_async_engine(build_database_url(settings), poolclass=NullPool)
        database = Database(
            engine=engine,
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
        )
        yield IntegrationDatabase(
            database=database,
            migrations=MigrationSnapshots(
                upgraded_tables=upgraded_tables,
                upgraded_enums=upgraded_enums,
                downgraded_tables=downgraded_tables,
                downgraded_enums=downgraded_enums,
            ),
        )
    finally:
        if database is not None:
            await database.engine.dispose()
        admin = await asyncpg.connect(
            host=base_settings.postgres_host,
            port=base_settings.postgres_port,
            database="postgres",
            user=base_settings.postgres_user,
            password=base_settings.postgres_password.get_secret_value(),
        )
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}" WITH (FORCE)')
        finally:
            await admin.close()


@pytest_asyncio.fixture(scope="session")
async def seeded_database(test_database: IntegrationDatabase) -> IntegrationDatabase:
    async with test_database.session_factory.begin() as session:
        await seed_database(session)
    return test_database
