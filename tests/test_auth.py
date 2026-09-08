from uuid import uuid4

import pytest
from pydantic import SecretStr

from ecommerce_ai_agent.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from ecommerce_ai_agent.config import Settings


def auth_settings() -> Settings:
    return Settings(
        _env_file=None,
        postgres_password=SecretStr("db"),
        jwt_secret=SecretStr("test-secret-that-is-at-least-32-bytes-long"),
    )


def test_argon2_password_hash_verifies_without_storing_plaintext() -> None:
    encoded = hash_password("customer-password")

    assert encoded != "customer-password"
    assert verify_password("customer-password", encoded) is True
    assert verify_password("wrong", encoded) is False


def test_jwt_round_trip_returns_subject_uuid() -> None:
    user_id = uuid4()

    token = create_access_token(user_id, auth_settings())

    assert decode_access_token(token, auth_settings()) == user_id


def test_invalid_jwt_is_rejected() -> None:
    with pytest.raises(ValueError):
        decode_access_token("not-a-token", auth_settings())
