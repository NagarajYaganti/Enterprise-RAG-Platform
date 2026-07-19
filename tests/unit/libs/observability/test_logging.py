import json
import logging

import pytest
from observability.logging import JSONFormatter, get_json_logger


def test_json_formatter_includes_request_and_tenant_id() -> None:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test-logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello world",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-1"
    record.tenant_id = "tenant-acme"

    formatted = json.loads(formatter.format(record))

    assert formatted["message"] == "hello world"
    assert formatted["request_id"] == "req-1"
    assert formatted["tenant_id"] == "tenant-acme"
    assert formatted["level"] == "INFO"


def test_json_formatter_defaults_missing_ids_to_none() -> None:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test-logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="no ids here",
        args=(),
        exc_info=None,
    )

    formatted = json.loads(formatter.format(record))

    assert formatted["request_id"] is None
    assert formatted["tenant_id"] is None


def test_get_json_logger_emits_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    logger = get_json_logger("test.observability.logging")
    logger.info("structured message", extra={"request_id": "req-2", "tenant_id": "tenant-b"})

    captured = capsys.readouterr()
    emitted = json.loads(captured.err.strip())

    assert emitted["message"] == "structured message"
    assert emitted["request_id"] == "req-2"
    assert emitted["tenant_id"] == "tenant-b"
