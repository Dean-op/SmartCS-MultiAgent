import logging

from tests.integration.conftest import EXPECTED_ENUMS, EXPECTED_TABLES, IntegrationDatabase

application_logger = logging.getLogger("ecommerce_ai_agent.llm.client")


def test_initial_migration_round_trip_creates_and_removes_business_schema(
    test_database: IntegrationDatabase,
) -> None:
    assert test_database.migrations.upgraded_tables == EXPECTED_TABLES
    assert test_database.migrations.upgraded_enums == EXPECTED_ENUMS
    assert test_database.migrations.downgraded_tables == set()
    assert test_database.migrations.downgraded_enums == set()


def test_alembic_does_not_disable_application_loggers(test_database: IntegrationDatabase) -> None:
    assert application_logger.disabled is False
