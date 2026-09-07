from ecommerce_ai_agent.knowledge import SearchResult
from ecommerce_ai_agent.retrieval_evaluation import EvaluationCase, hit_metrics


def test_hit_metrics_require_both_expected_source_and_chunk_text() -> None:
    cases = [
        EvaluationCase("q1", "refund.md", "七天"),
        EvaluationCase("q2", "shipping.md", "四十八小时"),
    ]
    rankings = [
        [
            SearchResult("1", "refund.md", "支持七天退货", 0.9),
            SearchResult("2", "shipping.md", "四十八小时无更新", 0.8),
        ],
        [
            SearchResult("3", "refund.md", "四十八小时无更新", 0.9),
            SearchResult("4", "shipping.md", "四十八小时无更新", 0.8),
        ],
    ]

    assert hit_metrics(cases, rankings) == {"hit_at_1": 0.5, "hit_at_3": 1.0}
