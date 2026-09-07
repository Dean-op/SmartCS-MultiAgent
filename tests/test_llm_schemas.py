import pytest
from pydantic import ValidationError


def test_route_decision_accepts_only_the_four_m6_routes() -> None:
    from ecommerce_ai_agent.llm.schemas import RouteDecision

    for route in ("order", "refund", "product", "general"):
        assert RouteDecision(route=route).route == route

    with pytest.raises(ValidationError):
        RouteDecision(route="supervisor")
