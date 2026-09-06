import pytest

from tests.integration.conftest import assert_safe_test_database_name


@pytest.mark.parametrize(
    "unsafe_name",
    ["ecommerce_agent", "postgres", "template1", "../ecommerce_agent_test", ""],
)
def test_database_fixture_refuses_to_manage_non_test_database_names(unsafe_name: str) -> None:
    with pytest.raises(RuntimeError, match="unsafe test database name"):
        assert_safe_test_database_name(unsafe_name)
