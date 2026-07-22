import logging
from pathlib import Path

from core.model_registry import get_default_embedding_model
from embedding.embedding_policy import SPREADSHEET_MIME_TYPE, decide_embedding_route

HTML_MIME = "text/html"


def test_spreadsheet_document_routes_to_the_tables_collection() -> None:
    outcome = decide_embedding_route(SPREADSHEET_MIME_TYPE, "en")

    assert outcome["collection_name"] == "chunks_tables"
    assert outcome["index_name"] == "chunks_tables"
    assert outcome["model_id"] == "BAAI/bge-small-en-v1.5"


def test_prose_document_keeps_todays_real_default_collection() -> None:
    outcome = decide_embedding_route(HTML_MIME, "en")

    default_model = get_default_embedding_model()
    assert outcome["collection_name"] == "chunks"
    assert outcome["index_name"] == "chunks"
    assert outcome["model_id"] == default_model["id"]
    assert outcome["model_version"] == default_model["version"]


def test_missing_policy_file_falls_back_to_the_real_default_model(tmp_path: Path) -> None:
    outcome = decide_embedding_route(SPREADSHEET_MIME_TYPE, "en", directory=str(tmp_path))

    default_model = get_default_embedding_model()
    assert outcome["model_id"] == default_model["id"]
    assert outcome["model_version"] == default_model["version"]
    assert outcome["collection_name"] == "chunks"
    assert outcome["index_name"] == "chunks"


def test_a_real_tenant_id_reaches_the_policy_decision_log() -> None:
    target_logger = logging.getLogger("core.policy_engine")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    target_logger.addHandler(handler)
    try:
        decide_embedding_route(HTML_MIME, "en", tenant_id="tenant-acme")
    finally:
        target_logger.removeHandler(handler)

    decision_records = [r for r in records if r.getMessage() == "policy_engine.decision"]
    assert decision_records[-1].tenant_id == "tenant-acme"  # type: ignore[attr-defined]
