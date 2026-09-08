from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True, slots=True)
class MetricScore:
    correct: int
    total: int

    @property
    def rate(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def as_dict(self) -> dict[str, int | float]:
        return {"correct": self.correct, "total": self.total, "rate": self.rate}


def values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            values_equal(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            values_equal(item, wanted) for item, wanted in zip(actual, expected, strict=True)
        )
    if (
        isinstance(actual, str)
        and isinstance(expected, (int, float))
        and not isinstance(expected, bool)
    ):
        try:
            return Decimal(actual) == Decimal(str(expected))
        except InvalidOperation:
            return False
    return actual == expected


def evaluate_metrics(
    cases: list[dict[str, Any]], observations: dict[str, dict[str, Any]]
) -> dict[str, MetricScore]:
    def exact(expected: str, actual: str) -> MetricScore:
        applicable = [case for case in cases if expected in case]
        correct = sum(
            values_equal(observations.get(case["id"], {}).get(actual), case[expected])
            for case in applicable
        )
        return MetricScore(correct, len(applicable))

    safety_cases = [case for case in cases if case.get("safety")]
    safety_correct = sum(
        observations.get(case["id"], {}).get("safety_passed") is True for case in safety_cases
    )
    task_correct = sum(
        observations.get(case["id"], {}).get("task_success") is True for case in cases
    )
    return {
        "router_accuracy": exact("expected_route", "route"),
        "agent_selection_accuracy": exact("expected_agents", "agents"),
        "tool_selection_accuracy": exact("expected_tools", "tools"),
        "tool_argument_accuracy": exact("expected_arguments", "arguments"),
        "task_success_rate": MetricScore(task_correct, len(cases)),
        "safety_authorization": MetricScore(safety_correct, len(safety_cases)),
    }
