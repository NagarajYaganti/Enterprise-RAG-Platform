import uuid
from typing import Any

from connectors.embeddings.sentence_transformers_provider import SentenceTransformersProvider
from connectors.keyword.client import get_opensearch_client
from connectors.keyword.opensearch_index import OpenSearchIndex, ensure_index
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.vectorstores.client import get_qdrant_client
from connectors.vectorstores.migrations import ensure_qdrant_collection
from connectors.vectorstores.qdrant_store import QdrantVectorStore
from core.interfaces import Chunker
from core.models import Document, EmbeddingRecord, ParsedDocument, Query, RetrievalFilters
from preprocessing.chunkers.fixed_size import FixedSizeChunker
from preprocessing.chunkers.structure_aware import StructureAwareChunker
from preprocessing.chunking_policy import decide_chunking_strategy
from preprocessing.language_detect import LanguageDetector
from preprocessing.pipeline import run_pipeline
from preprocessing.translator_stub import StubTranslator
from sqlalchemy.orm import Session

from retrieval.eval import GoldenQuery, run_harness
from retrieval.pipeline import RetrievalDependencies, retrieve
from retrieval.settings import RetrievalSettings

TENANT_ID = "tenant-chunk-tuning"
PRINCIPALS = ["chunk-tuning"]
MODEL_ID = "BAAI/bge-small-en-v1.5"


def _build_chunker(
    mime_type: str, raw_text: str, structural_elements: list[Any], directory: str | None
) -> tuple[Chunker, str]:
    """Same routing logic as ingestion.worker._build_chunker, but
    parameterized on `directory` so a candidate ChunkingPolicy rule
    variant (a temp-directory config/policies/chunking.yaml replacement)
    can be evaluated without ever touching the real production file --
    the same directory=tmp_path pattern already used by every other
    policy test since Phase 0.
    """
    outcome = decide_chunking_strategy(
        mime_type, raw_text, structural_elements, directory, tenant_id=TENANT_ID
    )
    strategy = outcome["strategy"]
    if strategy == "fixed_size":
        chunk_size = outcome.get("chunk_size", 500)
        overlap_pct = outcome.get("overlap_pct", 0.15)
        chunker: Chunker = FixedSizeChunker(
            chunk_size=chunk_size, overlap=int(chunk_size * overlap_pct)
        )
    else:
        chunker = StructureAwareChunker()
    return chunker, strategy


def evaluate_chunking_variant(
    documents: list[dict[str, Any]],
    golden_queries: list[GoldenQuery],
    rules_directory: str | None,
    k: int = 5,
) -> dict[str, float]:
    """Re-chunks every eval document through the REAL preprocessing
    pipeline under a candidate ChunkingPolicy rule set, embeds via the
    real local model into a fresh, isolated Qdrant collection + OpenSearch
    index, then runs the real retrieval.eval harness -- every component
    real, no shortcuts, per the Adaptive Policy Pattern's own "tune rules
    only via eval-harness evidence" rule.

    Relevance is scored at the DOCUMENT level (a retrieved chunk counts as
    a hit for its parent document_id), not by exact chunk id -- different
    rule variants produce different chunk boundaries/ids for the same
    document, so document-level relevance is the only identity stable
    across variants.
    """
    trial_id = uuid.uuid4().hex[:8]
    collection_name = f"chunk_tuning_{trial_id}"
    index_name = f"chunk_tuning_{trial_id}"

    from connectors.postgres.orm import Base
    from connectors.postgres.session import get_engine, get_sessionmaker

    engine = get_engine()
    # A fresh CI Postgres container has no tables at all yet -- every other
    # test/module in this codebase that opens its own session calls this
    # first (create_all is idempotent, a no-op against a long-lived dev
    # volume that already has the tables). Missing here caused a real CI
    # failure (relation "documents" does not exist) that a long-lived local
    # dev database masked.
    Base.metadata.create_all(engine)
    session: Session = get_sessionmaker(engine)()

    embedding_provider = SentenceTransformersProvider(MODEL_ID)
    qdrant_client = get_qdrant_client()
    ensure_qdrant_collection(
        qdrant_client, collection_name, dimension=embedding_provider.dimension()
    )
    vector_store = QdrantVectorStore(qdrant_client, collection_name)

    opensearch_client = get_opensearch_client()
    ensure_index(opensearch_client, index_name)
    keyword_index = OpenSearchIndex(opensearch_client, index_name)

    language_detector = LanguageDetector()
    document_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    document_id_by_chunk_id: dict[str, str] = {}

    try:
        for doc in documents:
            document_id = f"{trial_id}-{doc['id']}"
            parsed = ParsedDocument(
                tenant_id=TENANT_ID,
                document_id=document_id,
                raw_text=doc["text"],
                structural_elements=[],
                mime_type="text/plain",
                source_uri=f"eval://{document_id}",
                checksum=document_id,
                acl_principals=PRINCIPALS,
            )
            chunker, strategy = _build_chunker(
                parsed.mime_type, parsed.raw_text, parsed.structural_elements, rules_directory
            )
            chunks = run_pipeline(
                parsed, chunker, strategy, language_detector, StubTranslator(), version=1
            )
            for chunk in chunks:
                chunk.acl_principals = PRINCIPALS
                document_id_by_chunk_id[chunk.id] = doc["id"]

            document_repo.upsert(
                Document(
                    id=document_id,
                    tenant_id=TENANT_ID,
                    source_uri=parsed.source_uri,
                    mime_type=parsed.mime_type,
                    checksum=document_id,
                    version=1,
                    status="PARSED",
                )
            )
            chunk_repo.bulk_insert(chunks)
            session.commit()

            texts = [c.text for c in chunks]
            vectors = embedding_provider.embed(texts, MODEL_ID) if texts else []
            for chunk, vector in zip(chunks, vectors, strict=True):
                vector_store.upsert(
                    TENANT_ID,
                    [
                        EmbeddingRecord(
                            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk.id}:{MODEL_ID}")),
                            tenant_id=TENANT_ID,
                            document_id=document_id,
                            chunk_id=chunk.id,
                            vector=vector,
                            model_id=MODEL_ID,
                            model_version="1",
                            acl_principals=PRINCIPALS,
                        )
                    ],
                )
            keyword_index.upsert(TENANT_ID, chunks)

        deps = RetrievalDependencies(
            vector_store=vector_store,
            keyword_index=keyword_index,
            embedding_provider=embedding_provider,
            embedding_model_id=MODEL_ID,
            reranker=None,
            entity_extractor=None,
            llm_provider=None,
            llm_model_id="",
        )
        settings = RetrievalSettings()

        def retrieve_fn(query_text: str) -> list[str]:
            outcome = retrieve(
                session,
                deps,
                Query(id=str(uuid.uuid4()), tenant_id=TENANT_ID, session_id="s-1", text=query_text),
                PRINCIPALS,
                RetrievalFilters(),
                settings,
                [],
                top_k=k,
            )
            # Deduplicated, first-occurrence-rank order: retrieval.eval's
            # metrics assume one entry per distinct retrieved item at each
            # rank. A rule variant that splits one document into several
            # chunks can retrieve MULTIPLE chunks of the SAME document in
            # one top_k result set -- without deduplication, that document
            # would count as a hit at multiple ranks simultaneously,
            # inflating DCG past what IDCG (computed once per relevant
            # document) normalizes for, producing an nDCG > 1.0 (a real
            # bug caught by this module's own tests, not a hypothetical).
            seen: set[str] = set()
            document_ids: list[str] = []
            for sc in outcome.result.chunks:
                document_id = document_id_by_chunk_id.get(sc.chunk.id, sc.chunk.id)
                if document_id not in seen:
                    seen.add(document_id)
                    document_ids.append(document_id)
            return document_ids

        return run_harness(golden_queries, retrieve_fn, k=k)
    finally:
        for document_id in list(
            {f"{trial_id}-{doc['id']}" for doc in documents}
        ):
            chunk_repo.hard_delete_for_document(TENANT_ID, document_id)
            document_repo.hard_delete(TENANT_ID, document_id)
        session.commit()
        session.close()
        qdrant_client.delete_collection(collection_name)
        opensearch_client.indices.delete(index=f"{index_name}_*", ignore=[404])


def run_auto_tuning(
    documents: list[dict[str, Any]],
    golden_queries: list[GoldenQuery],
    candidate_rule_directories: dict[str, str | None],
    k: int = 5,
) -> dict[str, dict[str, float]]:
    """Runs the current real config/policies/chunking.yaml (pass
    directory=None for the baseline) plus each named candidate variant,
    returning a comparison table -- printed/logged as a human-readable
    report by the caller. Never auto-applied: per Section 4 Phase 3's own
    "proposed as a config diff for human review," this only measures and
    reports, it does not write config/policies/chunking.yaml.
    """
    return {
        name: evaluate_chunking_variant(documents, golden_queries, directory, k=k)
        for name, directory in candidate_rule_directories.items()
    }
