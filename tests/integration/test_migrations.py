from tests.integration.conftest import EXPECTED_ENUMS, EXPECTED_TABLES, IntegrationDatabase


def test_initial_migration_round_trip_creates_and_removes_business_schema(
    test_database: IntegrationDatabase,
) -> None:
    assert test_database.migrations.upgraded_tables == EXPECTED_TABLES
    assert test_database.migrations.upgraded_enums == EXPECTED_ENUMS
    assert test_database.migrations.downgraded_tables == set()
    assert test_database.migrations.downgraded_enums == set()
