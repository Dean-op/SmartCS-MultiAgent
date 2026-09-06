"""Wait for the running M0 API and verify its health contract."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

EXPECTED_DEPENDENCIES = {"postgres": "ok", "redis": "ok", "milvus": "ok"}


def fetch_json(url: str, timeout: float = 5.0) -> tuple[int, dict[str, Any]]:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - local URL
        payload = json.loads(response.read().decode("utf-8"))
        return response.status, payload


def run_smoke_test(base_url: str, wait_seconds: float) -> None:
    deadline = time.monotonic() + wait_seconds
    last_error = "API did not respond"

    while time.monotonic() < deadline:
        try:
            live_status, live_payload = fetch_json(f"{base_url}/health/live")
            ready_status, ready_payload = fetch_json(f"{base_url}/health/ready")
            if live_status != 200 or live_payload != {"status": "alive"}:
                raise RuntimeError(f"unexpected liveness response: {live_status} {live_payload}")
            if ready_status != 200:
                raise RuntimeError(f"unexpected readiness status: {ready_status}")
            if ready_payload.get("status") != "ready":
                raise RuntimeError(f"unexpected readiness response: {ready_payload}")
            if ready_payload.get("dependencies") != EXPECTED_DEPENDENCIES:
                raise RuntimeError(f"unexpected dependency status: {ready_payload}")
            print("M0 smoke test passed: API, PostgreSQL, Redis, and Milvus are ready.")
            return
        except (OSError, ValueError, RuntimeError, urllib.error.HTTPError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2)

    raise RuntimeError(f"M0 smoke test timed out after {wait_seconds}s; last error: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--wait-seconds", type=float, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_smoke_test(args.base_url.rstrip("/"), args.wait_seconds)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
