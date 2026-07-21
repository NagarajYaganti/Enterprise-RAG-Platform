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


def test_json_formatter_includes_arbitrary_extra_fields() -> None:
    """Phase-4 addition: previously only request_id/tenant_id from extra=
    ever reached the output — every other field was silently dropped.
    """
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test-logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="routing decision",
        args=(),
        exc_info=None,
    )
    record.model_id = "gpt-5.6-luna"
    record.candidates_considered = ["gpt-5.6-luna", "claude-sonnet-5"]

    formatted = json.loads(formatter.format(record))

    assert formatted["model_id"] == "gpt-5.6-luna"
    assert formatted["candidates_considered"] == ["gpt-5.6-luna", "claude-sonnet-5"]


def test_json_formatter_does_not_leak_internal_logrecord_attrs() -> None:
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test-logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )

    formatted = json.loads(formatter.format(record))

    for internal_key in ("msg", "args", "levelno", "pathname", "thread", "process"):
        assert internal_key not in formatted
