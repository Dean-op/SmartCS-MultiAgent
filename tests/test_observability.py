import logging
from decimal import Decimal

from ecommerce_ai_agent.observability import (
    observe_request,
    record_model_call,
    record_path,
    record_tool_call,
)


def test_request_observation_accumulates_path_usage_calls_cost_and_errors() -> None:
    with observe_request(
        "request-1",
        input_price_per_million=Decimal("3"),
        output_price_per_million=Decimal("12"),
    ) as observation:
        record_path("router")
        record_path("order_agent")
        record_model_call(input_tokens=100, output_tokens=25)
        record_model_call(input_tokens=20, output_tokens=5, error_type="ModelTimeoutError")
        record_tool_call("get_current_user_order")

    assert observation.request_id == "request-1"
    assert observation.path == ["router", "order_agent", "tool:get_current_user_order"]
    assert observation.model_calls == 2
    assert observation.tool_calls == 1
    assert observation.input_tokens == 120
    assert observation.output_tokens == 30
    assert observation.error_count == 1
    assert observation.error_types == ["ModelTimeoutError"]
    assert observation.estimated_cost_cny == Decimal("0.00072000")


def test_observation_functions_are_safe_outside_an_http_request() -> None:
    record_path("router")
    record_model_call(input_tokens=10, output_tokens=2)
    record_tool_call("get_product_by_sku")


def test_request_observation_logs_one_structured_summary(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="ecommerce_ai_agent.observability"):
        with observe_request(
            "request-2",
            input_price_per_million=Decimal("3"),
            output_price_per_million=Decimal("12"),
        ):
            record_path("router")

    record = next(record for record in caplog.records if record.message == "Request completed")
    assert record.request_id == "request-2"
    assert record.execution_path == "router"
    assert record.model_calls == 0
    assert record.tool_calls == 0
    assert record.input_tokens == 0
    assert record.output_tokens == 0
    assert record.estimated_cost_cny == 0.0
