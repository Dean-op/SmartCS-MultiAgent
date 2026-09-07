"""Compare Dense, Hybrid RRF, and Hybrid plus Reranker retrieval."""

import asyncio
import json
from pathlib import Path

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.knowledge import KnowledgeBase, SearchResult
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.retrieval_evaluation import hit_metrics, load_cases

CASES_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "retrieval_cases.json"


def labels(results: list[SearchResult]) -> list[str]:
    return [f"{result.source}#{result.chunk_id[:8]}" for result in results[:3]]


async def run() -> None:
    settings = Settings()
    model = BailianModel(settings)
    knowledge = KnowledgeBase(settings, model)
    cases = await asyncio.to_thread(load_cases, CASES_PATH)
    dense_rankings: list[list[SearchResult]] = []
    hybrid_rankings: list[list[SearchResult]] = []
    reranked_rankings: list[list[SearchResult]] = []
    try:
        for case in cases:
            dense_rankings.append(await knowledge.dense_search(case.query, limit=3))
            candidates = await knowledge.hybrid_search(
                case.query,
                limit=settings.hybrid_candidate_k,
            )
            hybrid_rankings.append(candidates[:3])
            reranked_rankings.append(await knowledge.rerank_candidates(case.query, candidates))
    finally:
        await knowledge.close()
        await model.close()

    comparisons = []
    for case, dense, hybrid, reranked in zip(
        cases,
        dense_rankings,
        hybrid_rankings,
        reranked_rankings,
        strict=True,
    ):
        if labels(dense) != labels(hybrid) or labels(hybrid) != labels(reranked):
            comparisons.append(
                {
                    "query": case.query,
                    "expected_source": case.expected_source,
                    "dense": labels(dense),
                    "hybrid": labels(hybrid),
                    "hybrid_rerank": labels(reranked),
                }
            )

    print(
        json.dumps(
            {
                "cases": len(cases),
                "dense": hit_metrics(cases, dense_rankings),
                "hybrid": hit_metrics(cases, hybrid_rankings),
                "hybrid_rerank": hit_metrics(cases, reranked_rankings),
                "ranking_changes": comparisons,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(run())
