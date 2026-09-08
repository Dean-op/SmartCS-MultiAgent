"""Run the final read-only HTTP demo against the local API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any


def configure_output(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


def api_call(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[Any, dict[str, str]]:
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(  # noqa: S310 - explicit local demo endpoint
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        response = urllib.request.urlopen(request, timeout=60)  # noqa: S310
    except urllib.error.HTTPError as exc:
        try:
            code = json.loads(exc.read().decode())["error"]["code"]
        except (KeyError, TypeError, ValueError):
            code = "http_error"
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {code}") from exc
    with response:
        content = json.loads(response.read().decode())
        return content, {key.lower(): value for key, value in response.headers.items()}


def run_demo(base_url: str, *, emit: Callable[[str], None] = print) -> None:
    customer_login, _ = api_call(
        base_url,
        "POST",
        "/api/v1/auth/login",
        payload={"email": "alice@example.com", "password": "customer-password"},
    )
    customer_token = customer_login["access_token"]
    scenarios = (
        ("普通对话", "你好，请介绍一下你能做什么。", False),
        ("订单查询", "我的订单 EC2026080016 现在是什么状态？", False),
        ("多轮记忆", "它有退款记录吗？", True),
        ("商品查询", "SKU ELEC-HUB-001 这个商品多少钱？", False),
        ("知识库问答", "平台的七天无理由退款政策是什么？", False),
        (
            "跨 Agent 协作",
            "查询订单 EC2026080016，同时告诉我相关退款单 RF2026080001 的状态。",
            False,
        ),
    )
    order_conversation_id = None
    emit("=== ecommerce-ai-agent M15 Demo ===")
    for index, (title, message, reuse_order_conversation) in enumerate(scenarios):
        payload = {"message": message}
        if reuse_order_conversation:
            payload["conversation_id"] = order_conversation_id
        response, headers = api_call(
            base_url,
            "POST",
            "/api/v1/chat",
            payload=payload,
            token=customer_token,
        )
        if index == 1:
            order_conversation_id = response["conversation_id"]
        emit(f"\n[{title}] {message}")
        emit(response["message"]["content"])
        emit(f"request_id={headers.get('x-request-id', 'n/a')}")

    admin_login, _ = api_call(
        base_url,
        "POST",
        "/api/v1/auth/login",
        payload={"email": "admin@example.com", "password": "admin-password"},
    )
    reviews, _ = api_call(
        base_url,
        "GET",
        "/api/v1/reviews/pending",
        token=admin_login["access_token"],
    )
    emit(f"\n[Human Review] 当前待审核记录：{len(reviews)} 条")
    emit("Demo 完成。退款写入与 approve/resume 请运行 scripts/refund_smoke_test.py。")


def main() -> int:
    configure_output(sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    try:
        run_demo(args.base_url.rstrip("/"))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Demo failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
