import json
import logging
from datetime import datetime, timezone
from typing import Any

# The standard logging.LogRecord attribute names (Python 3.12, including
# taskName added for asyncio task tracking) — anything else set on a record
# (i.e. passed via logger.info(..., extra={...})) is caller-supplied
# structured context and gets included in the JSON payload verbatim.
# Phase-4 addition: previously this formatter only ever surfaced
# request_id/tenant_id from extra, silently dropping everything else passed
# via extra= — discovered while wiring model_router.py's routing-decision
# log line, which needs arbitrary structured fields (model_id, task,
# complexity, ...), not just the two tenant/request identifiers.
_STANDARD_LOG_RECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
    }
)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "tenant_id": getattr(record, "tenant_id", None),
        }
        extra_fields = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOG_RECORD_ATTRS and key not in ("request_id", "tenant_id")
        }
        payload.update(extra_fields)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def get_json_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not any(isinstance(h.formatter, JSONFormatter) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
