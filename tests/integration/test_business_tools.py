import json

import pytest

from ecommerce_ai_agent.business_tools import TOOL_DEFINITIONS, BusinessTools
from tests.integration.conftest import IntegrationDatabase


def test_tool_schemas_never_allow_the_model_to_supply_user_identity() -> None:
    schemas = {tool["function"]["name"]: tool["function"] for tool in TOOL_DEFINITIONS}

    assert set(schemas) == {
        "get_current_user_order",
        "get_product_by_sku",
        "get_current_user_refund",
    }
    for function in schemas.values():
        parameters = function["parameters"]
        assert "user_id" not in parameters["properties"]
        assert parameters["additionalProperties"] is False


@pytest.mark.asyncio
async def test_order_tool_uses_trusted_user_and_returns_compact_business_data(
    seeded_database: IntegrationDatabase,
) -> None:
    tools = BusinessTools(seeded_database.session_factory, "alice@example.com")

    owned = json.loads(await tools.run("get_current_user_order", '{"order_number":"EC2026080016"}'))
    another_users_order = json.loads(
        await tools.run("get_current_user_order", '{"order_number":"EC2026080002"}')
    )

    assert owned["found"] is True
    assert owned["order_number"] == "EC2026080016"
    assert owned["shipment"]["status"] == "delivered"
    assert owned["items"]
    assert "user_id" not in owned
    assert another_users_order == {"found": False}


@pytest.mark.asyncio
async def test_product_tool_returns_money_as_decimal_string(
    seeded_database: IntegrationDatabase,
) -> None:
    tools = BusinessTools(seeded_database.session_factory, "alice@example.com")

    result = json.loads(await tools.run("get_product_by_sku", '{"sku":"ELEC-HUB-001"}'))

    assert result == {
        "found": True,
        "sku": "ELEC-HUB-001",
        "name": "USB-C 多功能扩展坞",
        "description": "M2 开发测试商品：USB-C 多功能扩展坞",
        "unit_price": "299.00",
        "is_active": True,
    }


@pytest.mark.asyncio
async def test_refund_tool_applies_current_user_order_ownership(
    seeded_database: IntegrationDatabase,
) -> None:
    tools = BusinessTools(seeded_database.session_factory, "alice@example.com")

    owned = json.loads(
        await tools.run("get_current_user_refund", '{"refund_number":"RF2026080001"}')
    )
    another_users_refund = json.loads(
        await tools.run("get_current_user_refund", '{"refund_number":"RF2026080002"}')
    )

    assert owned["found"] is True
    assert owned["refund_number"] == "RF2026080001"
    assert owned["amount"] == "50.00"
    assert owned["status"] == "requested"
    assert "order_id" not in owned
    assert another_users_refund == {"found": False}


@pytest.mark.asyncio
async def test_tool_rejects_unknown_name_and_invalid_arguments_without_database_access(
    seeded_database: IntegrationDatabase,
) -> None:
    tools = BusinessTools(seeded_database.session_factory, "alice@example.com")

    unknown = json.loads(await tools.run("unknown", "{}"))
    untrusted_argument = json.loads(
        await tools.run(
            "get_current_user_order",
            '{"order_number":"EC2026080016","user_id":"attacker"}',
        )
    )

    assert unknown == {"error": "unknown_tool"}
    assert untrusted_argument == {"error": "invalid_arguments"}
