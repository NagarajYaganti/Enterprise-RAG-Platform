"""Phase 3 retrofit — chunking auto-tuning loop (Section 4 Phase 3:
"harness can re-chunk the eval corpus under alternative ChunkingPolicy
rules and compare retrieval scores... winning rules are proposed as a
config diff for human review, never auto-applied"). Every number here
comes from actually running the harness, per CLAUDE.md's rule against
reporting uncomputed metrics.
"""

from pathlib import Path

from core.models import ParsedDocument
from preprocessing.language_detect import LanguageDetector
from preprocessing.pipeline import run_pipeline
from preprocessing.translator_stub import StubTranslator
from retrieval.chunk_tuning import _build_chunker, run_auto_tuning

from tests.fixtures.eval_corpus.loader import load_eval_documents, load_golden_queries

# A long document from the corpus specifically added for this loop (see
# documents.yaml's own comment) -- short docs elsewhere in the corpus
# produce one chunk regardless of policy, proving nothing.
LONG_DOC_ID = "doc-23"


def _small_chunk_size_rules(tmp_path: Path) -> str:
    # A rule with no `when` clause matches unconditionally (a valid
    # catch-all per core.policy_engine's own docstring) -- forces
    # fixed_size with a small chunk_size regardless of any signal, so a
    # long document splits into multiple real chunks.
    (tmp_path / "chunking.yaml").write_text(
        """
policy: chunking
version: "1"
rules:
  - name: force_small_fixed_size
    when: {}
    then:
      strategy: fixed_size
      chunk_size: 30
      overlap_pct: 0.1
fallback:
  strategy: fixed_size
  chunk_size: 30
  overlap_pct: 0.1
"""
    )
    return str(tmp_path)


def test_baseline_and_small_chunk_size_candidate_produce_different_chunk_counts(
    tmp_path: Path,
) -> None:
    documents = {doc["id"]: doc for doc in load_eval_documents()}
    long_doc_text = documents[LONG_DOC_ID]["text"]
    parsed = ParsedDocument(
        tenant_id="tenant-eval",
        document_id=LONG_DOC_ID,
        raw_text=long_doc_text,
        structural_elements=[],
        mime_type="text/plain",
        source_uri="eval://doc-23",
        checksum="doc-23",
    )
    language_detector = LanguageDetector()

    baseline_chunker, baseline_strategy = _build_chunker(
        parsed.mime_type, parsed.raw_text, parsed.structural_elements, None
    )
    baseline_chunks = run_pipeline(
        parsed, baseline_chunker, baseline_strategy, language_detector, StubTranslator(), version=1
    )

    candidate_dir = _small_chunk_size_rules(tmp_path)
    candidate_chunker, candidate_strategy = _build_chunker(
        parsed.mime_type, parsed.raw_text, parsed.structural_elements, candidate_dir
    )
    candidate_chunks = run_pipeline(
        parsed,
        candidate_chunker,
        candidate_strategy,
        language_detector,
        StubTranslator(),
        version=1,
    )

    assert len(baseline_chunks) == 1, (
        f"expected the real production default (chunk_size=500) to keep this "
        f"document as one chunk, got {len(baseline_chunks)}"
    )
    assert len(candidate_chunks) > len(baseline_chunks), (
        f"expected a smaller chunk_size to split doc-23 into more real chunks, "
        f"got {len(candidate_chunks)} vs baseline's {len(baseline_chunks)}"
    )


def test_run_auto_tuning_reports_real_metrics_for_baseline_and_candidate(
    tmp_path: Path,
) -> None:
    documents = load_eval_documents()
    golden_queries = load_golden_queries()
    candidate_dir = _small_chunk_size_rules(tmp_path)

    report = run_auto_tuning(
        documents,
        golden_queries,
        {"baseline": None, "small_chunk_size": candidate_dir},
        k=5,
    )

    print("\n--- Chunking auto-tuning report (never auto-applied) ---")
    for name, metrics in report.items():
        print(f"{name}: {metrics}")

    assert set(report.keys()) == {"baseline", "small_chunk_size"}
    for metrics in report.values():
        assert "recall@5" in metrics
        assert "mrr" in metrics
        assert "ndcg@5" in metrics
        # real numbers, not fabricated: every metric must be a valid
        # [0, 1] score actually computed by run_harness.
        assert all(0.0 <= v <= 1.0 for v in metrics.values())
