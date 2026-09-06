import pytest
from pydantic import SecretStr, ValidationError

from ecommerce_ai_agent.config import Settings


def test_settings_use_local_dependency_hosts_by_default() -> None:
    settings = Settings(_env_file=None, postgres_password=SecretStr("test-password"))

    assert settings.postgres_host == "localhost"
    assert settings.redis_host == "localhost"
    assert settings.milvus_host == "localhost"


def test_settings_require_a_postgres_password() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
