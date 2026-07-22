import logging
from pathlib import Path

from preprocessing.chunking_policy import FALLBACK_OUTCOME, decide_chunking_strategy

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_structured_high_density_document_routes_to_structure_aware() -> None:
    # 13 tokens, 3 structural elements -> density ~231, well over the
    # gte: 1.0 threshold in config/policies/chunking-policy.yaml.
    outcome = decide_chunking_strategy(
        DOCX_MIME,
        "Section One heading and a short paragraph of body text under it.",
        [{"category": "Title", "text": "One"}, {"text": "a"}, {"text": "b"}],
    )
    assert outcome["strategy"] == "structure_aware"


def test_spreadsheet_routes_to_structure_aware_regardless_of_density() -> None:
    outcome = decide_chunking_strategy(XLSX_MIME, "irrelevant", [])
    assert outcome["strategy"] == "structure_aware"


def test_low_density_document_routes_to_fixed_size() -> None:
    # 2001 tokens, 1 structural element -> density ~0.5, under the
    # gte: 1.0 threshold, and under the lt: 1.0 fixed-size rule instead.
    outcome = decide_chunking_strategy(DOCX_MIME, "word " * 2000, [{"text": "only one element"}])
    assert outcome["strategy"] == "fixed_size"
    assert outcome["chunk_size"] == 500
    assert outcome["overlap_pct"] == 0.15


def test_missing_policy_file_falls_back_safely(tmp_path: Path) -> None:
    outcome = decide_chunking_strategy(
        DOCX_MIME, "anything", [], directory=str(tmp_path)
    )
    assert outcome == FALLBACK_OUTCOME


def test_a_real_tenant_id_reaches_the_policy_decision_log() -> None:
    target_logger = logging.getLogger("core.policy_engine")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    target_logger.addHandler(handler)
    try:
        decide_chunking_strategy(DOCX_MIME, "anything", [], tenant_id="tenant-acme")
    finally:
        target_logger.removeHandler(handler)

    decision_records = [r for r in records if r.getMessage() == "policy_engine.decision"]
    assert decision_records[-1].tenant_id == "tenant-acme"  # type: ignore[attr-defined]
