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


def test_model_settings_are_read_from_environment_without_exposing_api_key(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "temporary-test-key")
    monkeypatch.setenv(
        "BAILIAN_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("LLM_MODEL", "qwen3.8-27b")

    settings = Settings(_env_file=None, postgres_password=SecretStr("test-password"))

    assert settings.dashscope_api_key.get_secret_value() == "temporary-test-key"
    assert str(settings.bailian_base_url).startswith(
        "https://workspace.cn-beijing.maas.aliyuncs.com"
    )
    assert settings.llm_model == "qwen3.8-27b"
    assert "temporary-test-key" not in repr(settings)


def test_development_user_identity_comes_from_server_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEVELOPMENT_USER_EMAIL", "alice@example.com")

    settings = Settings(_env_file=None, postgres_password=SecretStr("test-password"))

    assert settings.development_user_email == "alice@example.com"


def test_model_provider_credentials_are_optional_for_non_llm_commands(monkeypatch) -> None:
    for variable in ("DASHSCOPE_API_KEY", "BAILIAN_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(variable, raising=False)

    settings = Settings(_env_file=None, postgres_password=SecretStr("test-password"))

    assert settings.dashscope_api_key is None
    assert settings.bailian_base_url is None
    assert settings.llm_model is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_timeout_seconds", 0),
        ("llm_max_retries", 6),
        ("llm_temperature", 2.1),
        ("llm_max_completion_tokens", 0),
    ],
)
def test_model_runtime_settings_reject_unsafe_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            postgres_password=SecretStr("test-password"),
            **{field: value},
        )
