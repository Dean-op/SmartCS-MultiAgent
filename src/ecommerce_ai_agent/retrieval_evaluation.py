import json
from dataclasses import dataclass
from pathlib import Path

from ecommerce_ai_agent.knowledge import SearchResult


@dataclass(frozen=True)
class EvaluationCase:
    query: str
    expected_source: str
    expected_contains: str


def load_cases(path: Path) -> list[EvaluationCase]:
    return [EvaluationCase(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def hit_metrics(
    cases: list[EvaluationCase], rankings: list[list[SearchResult]]
) -> dict[str, float]:
    if len(cases) != len(rankings):
        raise ValueError("each evaluation case requires one ranking")
    if not cases:
        return {"hit_at_1": 0.0, "hit_at_3": 0.0}

    def matches(case: EvaluationCase, result: SearchResult) -> bool:
        return result.source == case.expected_source and case.expected_contains in result.content

    hit_at_1 = sum(
        bool(results and matches(case, results[0]))
        for case, results in zip(cases, rankings, strict=True)
    )
    hit_at_3 = sum(
        any(matches(case, result) for result in results[:3])
        for case, results in zip(cases, rankings, strict=True)
    )
    return {
        "hit_at_1": hit_at_1 / len(cases),
        "hit_at_3": hit_at_3 / len(cases),
    }
