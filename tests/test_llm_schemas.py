import pytest
from pydantic import ValidationError


def test_route_decision_rejects_unknown_routes() -> None:
    from ecommerce_ai_agent.llm.schemas import RouteDecision

    for route in ("order", "refund", "product", "general"):
        assert RouteDecision(route=route).route == route

    with pytest.raises(ValidationError):
        RouteDecision(route="supervisor")


def test_m7_route_and_supervisor_plan_allow_only_minimal_unique_specialists() -> None:
    from ecommerce_ai_agent.llm.schemas import RouteDecision, SupervisorPlan

    assert RouteDecision(route="complex").route == "complex"
    assert SupervisorPlan(steps=["order", "refund"]).steps == ("order", "refund")

    for steps in (["order"], ["order", "order"], ["order", "general"]):
        with pytest.raises(ValidationError):
            SupervisorPlan(steps=steps)
