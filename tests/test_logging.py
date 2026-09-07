import json
import logging

from ecommerce_ai_agent.logging import JsonFormatter, configure_logging


def test_json_formatter_emits_core_fields_and_structured_context() -> None:
    record = logging.LogRecord(
        name="ecommerce_ai_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="application started",
        args=(),
        exc_info=None,
    )
    record.environment = "test"
    record.provider = "bailian"
    record.model = "qwen3.8-27b"
    record.operation = "structured"
    record.latency_ms = 12.34
    record.outcome = "success"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "ecommerce_ai_agent.test"
    assert payload["message"] == "application started"
    assert payload["environment"] == "test"
    assert payload["provider"] == "bailian"
    assert payload["model"] == "qwen3.8-27b"
    assert payload["operation"] == "structured"
    assert payload["latency_ms"] == 12.34
    assert payload["outcome"] == "success"
    assert payload["timestamp"].endswith("Z")


def test_logging_configuration_suppresses_http_client_info_logs(capsys) -> None:
    configure_logging("INFO")

    logging.getLogger("httpx").info("noisy health probe")
    logging.getLogger("httpx2").info("sensitive provider URL")
    logging.getLogger("ecommerce_ai_agent").info("useful application event")

    captured = capsys.readouterr()
    assert "useful application event" in captured.err
    assert "noisy health probe" not in captured.err
    assert "sensitive provider URL" not in captured.err
