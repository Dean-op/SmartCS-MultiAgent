"""Run the explicit M13 whole-agent evaluation against real local dependencies."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from ecommerce_ai_agent.agent_evaluation import evaluate_metrics, values_equal
from ecommerce_ai_agent.business_tools import BusinessTools
from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.database import create_database
from ecommerce_ai_agent.knowledge import KnowledgeBase
from ecommerce_ai_agent.llm.client import BailianModel
from ecommerce_ai_agent.seed import seed_id
from ecommerce_ai_agent.workflow import build_chat_workflow

CASES_PATH = Path(__file__).parents[1] / "evaluation" / "agent_cases.json"


def contains(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(
            key in actual and contains(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list) and isinstance(actual, list):
        return len(actual) == len(expected) and all(
            contains(item, wanted) for item, wanted in zip(actual, expected, strict=True)
        )
    return values_equal(actual, expected)


class RecordingBusinessTools(BusinessTools):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def run(self, name: str, arguments: str, user_id) -> str:
        result = await super().run(name, arguments, user_id)
        self.calls.append((name, json.loads(arguments), json.loads(result)))
        return result

    async def request_refund(self, arguments: str, user_id, thread_id: str) -> str:
        result = await super().request_refund(arguments, user_id, thread_id)
        self.calls.append(("request_refund", json.loads(arguments), json.loads(result)))
        return result


def agent_names(path: list[str]) -> list[str]:
    names: list[str] = []
    for node in path:
        if node.endswith("_agent"):
            name = node.removesuffix("_agent")
            if name not in names:
                names.append(name)
    return names


def final_answer(updates: list[dict[str, Any]]) -> str:
    for update in reversed(updates):
        payload = next(iter(update.values()))
        if not isinstance(payload, dict):
            continue
        for message in reversed(payload.get("messages", [])):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


async def evaluate_agent_case(case, workflow, tools) -> dict[str, Any]:
    tools.calls.clear()
    user_id = seed_id(f"user:{case['actor_email']}")
    updates = [
        update
        async for update in workflow.astream(
            {
                "messages": [{"role": "user", "content": case["query"]}],
                "user_id": str(user_id),
                "tool_used": False,
            },
            {"configurable": {"thread_id": f"{user_id}:m13-{case['id']}"}},
            stream_mode="updates",
        )
    ]
    path = [next(iter(update)) for update in updates]
    route = updates[0]["router"]["route"]
    tools_used = [call[0] for call in tools.calls]
    arguments = [call[1] for call in tools.calls]
    results = [call[2] for call in tools.calls]
    answer = final_answer(updates)
    structural = (
        route == case["expected_route"]
        and agent_names(path) == case["expected_agents"]
        and tools_used == case["expected_tools"]
        and (
            "expected_arguments" not in case or values_equal(arguments, case["expected_arguments"])
        )
        and ("expected_results" not in case or contains(results, case["expected_results"]))
        and ("answer_contains" not in case or case["answer_contains"] in answer)
        and bool(answer)
    )
    observation: dict[str, Any] = {
        "route": route,
        "agents": agent_names(path),
        "tools": tools_used,
        "arguments": arguments,
        "results": results,
        "task_success": structural,
    }
    if case.get("safety"):
        observation["safety_passed"] = structural and all(
            "user_id" not in argument for argument in arguments
        )
    return observation


async def tokens(client: httpx.AsyncClient) -> dict[str, str]:
    credentials = {
        "alice@example.com": "customer-password",
        "admin@example.com": "admin-password",
    }
    result = {}
    for email, password in credentials.items():
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        response.raise_for_status()
        result[email] = response.json()["access_token"]
    return result


async def evaluate_non_agent_cases(cases, tools) -> dict[str, dict[str, Any]]:
    observations = {}
    api_url = os.getenv("AGENT_API_URL", "http://localhost:8000")
    async with httpx.AsyncClient(base_url=api_url, timeout=30) as client:
        auth_tokens = await tokens(client)
        for case in cases:
            if case["kind"] == "http":
                headers = {}
                if email := case.get("actor_email"):
                    headers["Authorization"] = f"Bearer {auth_tokens[email]}"
                response = await client.request(
                    case["method"],
                    case["path"],
                    headers=headers,
                    json=case.get("body"),
                )
                passed = response.status_code == case["expected_status"]
                observations[case["id"]] = {
                    "status": response.status_code,
                    "task_success": passed,
                    "safety_passed": passed,
                }
            else:
                arguments = json.dumps(
                    {
                        "order_number": "EC2026080012",
                        "amount": "1.00",
                        "reason": "M13 duplicate guard",
                    }
                )
                user_id = seed_id("user:bob@example.com")
                thread_id = f"{user_id}:m13-duplicate-refund"
                await tools.request_refund(arguments, user_id, thread_id)
                result = json.loads(await tools.request_refund(arguments, user_id, thread_id))
                passed = result.get("outcome") == case["expected_outcome"]
                observations[case["id"]] = {
                    "outcome": result.get("outcome"),
                    "task_success": passed,
                    "safety_passed": passed,
                }
    return observations


async def run() -> int:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    settings = Settings()
    database = create_database(settings)
    model = BailianModel(settings)
    knowledge = KnowledgeBase(settings, model)
    tools = RecordingBusinessTools(database.session_factory, settings)
    workflow = build_chat_workflow(model, tools, knowledge)
    observations: dict[str, dict[str, Any]] = {}
    try:
        for case in cases:
            if case["kind"] == "agent":
                try:
                    observations[case["id"]] = await evaluate_agent_case(case, workflow, tools)
                except Exception as exc:  # keep failed cases visible in the report
                    observations[case["id"]] = {
                        "task_success": False,
                        "error": type(exc).__name__,
                    }
        system_cases = [case for case in cases if case["kind"] != "agent"]
        observations.update(await evaluate_non_agent_cases(system_cases, tools))
    finally:
        await knowledge.close()
        await model.close()
        await database.engine.dispose()

    metrics = evaluate_metrics(cases, observations)
    failures = [
        {"id": case["id"], "observation": observations[case["id"]]}
        for case in cases
        if not observations[case["id"]]["task_success"]
    ]
    report = {
        "cases": len(cases),
        "model": settings.llm_model,
        "metrics": {name: score.as_dict() for name, score in metrics.items()},
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        raise SystemExit(asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop))
    raise SystemExit(asyncio.run(run()))
