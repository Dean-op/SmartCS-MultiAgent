import json
import logging
from datetime import UTC, datetime

CONTEXT_FIELDS = (
    "environment",
    "dependency",
    "provider",
    "model",
    "operation",
    "latency_ms",
    "outcome",
    "error_type",
    "tool_name",
    "request_id",
    "trace_id",
    "span_id",
    "execution_path",
    "http_method",
    "http_path",
    "http_status_code",
    "model_calls",
    "tool_calls",
    "input_tokens",
    "output_tokens",
    "estimated_cost_cny",
    "error_count",
    "error_types",
    "safety_action",
    "safety_layer",
    "safety_categories",
    "pii_count",
    "content_hash",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in CONTEXT_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers[:] = [
        existing
        for existing in root_logger.handlers
        if not isinstance(existing.formatter, JsonFormatter)
    ]
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
