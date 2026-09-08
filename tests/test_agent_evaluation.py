import json
from pathlib import Path

from ecommerce_ai_agent.agent_evaluation import evaluate_metrics


def test_agent_metrics_use_only_applicable_cases_as_denominator() -> None:
    cases = [
        {
            "id": "order-ok",
            "expected_route": "order",
            "expected_agents": ["order"],
            "expected_tools": ["get_current_user_order"],
            "expected_arguments": [{"order_number": "EC1"}],
            "safety": False,
        },
        {
            "id": "ownership",
            "expected_route": "order",
            "expected_agents": ["order"],
            "expected_tools": ["get_current_user_order"],
            "expected_arguments": [{"order_number": "EC2"}],
            "safety": True,
        },
        {"id": "unauthenticated", "safety": True},
    ]
    observations = {
        "order-ok": {
            "route": "order",
            "agents": ["order"],
            "tools": ["get_current_user_order"],
            "arguments": [{"order_number": "EC1"}],
            "task_success": True,
        },
        "ownership": {
            "route": "refund",
            "agents": ["refund"],
            "tools": ["get_current_user_refund"],
            "arguments": [{"refund_number": "RF1"}],
            "task_success": False,
            "safety_passed": True,
        },
        "unauthenticated": {"task_success": True, "safety_passed": False},
    }

    metrics = evaluate_metrics(cases, observations)

    assert metrics["router_accuracy"].as_dict() == {
        "correct": 1,
        "total": 2,
        "rate": 0.5,
    }
    assert metrics["tool_argument_accuracy"].total == 2
    assert metrics["task_success_rate"].as_dict() == {
        "correct": 2,
        "total": 3,
        "rate": 2 / 3,
    }
    assert metrics["safety_authorization"].as_dict() == {
        "correct": 1,
        "total": 2,
        "rate": 0.5,
    }


def test_agent_dataset_covers_routes_complex_tools_and_authorization() -> None:
    path = Path(__file__).parents[1] / "evaluation" / "agent_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))

    assert len(cases) == 20
    assert {case["expected_route"] for case in cases if "expected_route" in case} == {
        "order",
        "refund",
        "product",
        "knowledge",
        "general",
        "complex",
    }
    assert sum(case.get("expected_route") == "complex" for case in cases) >= 3
    assert sum(bool(case.get("safety")) for case in cases) >= 4
    assert {tool for case in cases for tool in case.get("expected_tools", [])} >= {
        "get_current_user_order",
        "get_current_user_refund",
        "get_product_by_sku",
        "request_refund",
    }


def test_tool_argument_metric_treats_decimal_json_string_as_same_number() -> None:
    cases = [{"id": "refund", "expected_arguments": [{"amount": 99999}]}]
    observations = {"refund": {"arguments": [{"amount": "99999"}], "task_success": True}}

    score = evaluate_metrics(cases, observations)["tool_argument_accuracy"]

    assert score.correct == score.total == 1
