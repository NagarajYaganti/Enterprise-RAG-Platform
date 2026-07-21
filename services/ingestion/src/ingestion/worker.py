import tempfile
from pathlib import Path
from typing import Any

from arq.connections import RedisSettings
from connectors.parser_policy import decide_parser_route
from connectors.parser_registry import ParserRegistry, UnsupportedMimeTypeError
from connectors.parsers.password_check import is_password_protected
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.interfaces import Chunker
from core.models import Document, DocumentStatus, ParsedDocument
from preprocessing.chunkers.fixed_size import FixedSizeChunker
from preprocessing.chunkers.structure_aware import StructureAwareChunker
from preprocessing.chunking_policy import decide_chunking_strategy
from preprocessing.language_detect import LanguageDetector
from preprocessing.pipeline import run_pipeline
from preprocessing.translator_stub import StubTranslator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.orm import Session

from ingestion.dedupe import determine_version
from ingestion.queue import get_redis_settings
from ingestion.storage import download_fileobj, get_object_size, get_s3_client


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    # ASSUMPTION: 50 MB is a reasonable starting ceiling for the document
    # types this platform parses (policy docs, spreadsheets, slide decks,
    # short audio clips) -- not derived from a customer-stated limit. This
    # is a reject-oversized-files ceiling, not streaming/chunked parsing:
    # every parser today still reads the whole file into memory, so this
    # exists to fail fast and predictably rather than to bound memory use
    # precisely.
    max_document_size_bytes: int = 50_000_000


def _build_chunker(
    mime_type: str, raw_text: str, structural_elements: list[Any]
) -> tuple[Chunker, str]:
    """ChunkingPolicy replaces the previously-hardcoded StructureAwareChunker
    (verified: it was used for EVERY document regardless of type) -- the
    policy's outcome selects the strategy per docs/RETROFIT-AUDIT.md's
    Phase 1 retrofit plan.
    """
    outcome = decide_chunking_strategy(mime_type, raw_text, structural_elements)
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


def _mark_terminal(
    document_repo: DocumentRepository,
    session: Session,
    tenant_id: str,
    document_id: str,
    status: DocumentStatus,
    failure_reason: str,
) -> Document:
    """Used for parsing-stage failures (QUARANTINED/FAILED_PARSE/
    UNSUPPORTED), which happen before parsed.checksum even exists -- there
    is no new Document to build, only the existing UPLOADED row (created by
    ingestion.api's upload endpoint) to update in place.
    """
    existing = document_repo.get(tenant_id, document_id)
    if existing is None:
        raise ValueError(f"no document row for {tenant_id}/{document_id} to mark {status!r}")
    document = document_repo.upsert(
        Document(**{**existing.model_dump(), "status": status, "failure_reason": failure_reason})
    )
    session.commit()
    return document


def process_parsed_document(
    session: Session,
    language_detector: LanguageDetector,
    tenant_id: str,
    document_id: str,
    mime_type: str,
    source_uri: str,
    parsed: ParsedDocument,
) -> Document:
    """dedupe check -> preprocess -> persist, for a document that's ALREADY
    been parsed. Shared by process_document (parses from our own upload via
    S3/MinIO first) and ingestion.sync.run_sync (a SourceConnector already
    parsed it via its own internal parser_registry, fetching from an
    external source, not our own bucket) -- extracted so sync doesn't
    duplicate the chunking-policy/persistence logic.
    """
    document_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)

    decision = determine_version(document_repo, tenant_id, source_uri, parsed.checksum)

    document = document_repo.upsert(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            source_uri=source_uri,
            mime_type=mime_type,
            checksum=parsed.checksum,
            version=decision.version,
            status="PARSING",
            acl_principals=parsed.acl_principals,
        )
    )
    session.commit()

    if decision.is_exact_duplicate:
        document = document_repo.upsert(
            Document(**{**document.model_dump(), "status": "PARSED"})
        )
        session.commit()
        return document

    try:
        chunker, strategy = _build_chunker(mime_type, parsed.raw_text, parsed.structural_elements)
        chunks = run_pipeline(
            parsed,
            chunker,
            strategy,
            language_detector,
            StubTranslator(),
            version=decision.version,
        )

        chunk_repo.supersede_for_document(tenant_id, document_id)
        chunk_repo.bulk_insert(chunks)

        document = document_repo.upsert(
            Document(**{**document.model_dump(), "status": "PARSED"})
        )
        session.commit()
    except Exception:
        document = document_repo.upsert(
            Document(**{**document.model_dump(), "status": "FAILED"})
        )
        session.commit()
        raise

    return document


def process_document(
    session: Session,
    s3_client: object,
    parser_registry: ParserRegistry,
    language_detector: LanguageDetector,
    tenant_id: str,
    document_id: str,
    bucket: str,
    key: str,
    mime_type: str,
    settings: IngestionSettings | None = None,
) -> Document:
    """Core ingestion pipeline: size check -> download -> dedupe check ->
    parse -> preprocess -> persist. Kept independent of arq's ctx mechanism
    so it can be called directly in tests without a live worker process.

    The size check runs first, via a HEAD request against the object's
    metadata, before any download -- a ceiling, not true streaming (every
    parser here still reads its input in full once downloaded); oversized
    files resolve to UNSUPPORTED rather than being downloaded and then
    exhausting memory partway through parsing.

    Parsing-stage failures resolve to a distinct terminal status
    (QUARANTINED/FAILED_PARSE/UNSUPPORTED) instead of leaving the document
    stuck at its initial UPLOADED status forever -- previously, any
    exception during download/parse (corrupt file, unsupported mime type,
    OCR/STT error) happened before any try/except existed at all. These are
    treated as permanent, not retriable (retrying the same job can never
    make a password-protected file un-encrypted or an unknown mime type
    known), so this returns normally rather than re-raising -- unlike the
    chunking/persistence failure path below, which is unchanged.
    """
    document_repo = DocumentRepository(session)
    source_uri = f"s3://{bucket}/{key}"
    settings = settings or IngestionSettings()

    try:
        size_bytes = get_object_size(s3_client, bucket, key)
    except Exception as exc:
        return _mark_terminal(
            document_repo, session, tenant_id, document_id, "FAILED_PARSE", str(exc)
        )

    if size_bytes > settings.max_document_size_bytes:
        return _mark_terminal(
            document_repo,
            session,
            tenant_id,
            document_id,
            "UNSUPPORTED",
            f"document size {size_bytes} exceeds max_document_size_bytes "
            f"({settings.max_document_size_bytes})",
        )

    try:
        with tempfile.NamedTemporaryFile(suffix=Path(key).suffix) as tmp:
            download_fileobj(s3_client, bucket, key, tmp)
            tmp.flush()
            tmp_path = Path(tmp.name)

            if is_password_protected(tmp_path, mime_type):
                return _mark_terminal(
                    document_repo,
                    session,
                    tenant_id,
                    document_id,
                    "QUARANTINED",
                    "password-protected file",
                )

            # ParserPolicy replaces raising UnsupportedMimeTypeError as the
            # primary "can we even handle this?" gate -- an unmapped mime
            # type now resolves gracefully via the policy engine instead of
            # an exception the caller must catch.
            route_outcome = decide_parser_route(mime_type)
            if route_outcome["route"] == "unsupported":
                return _mark_terminal(
                    document_repo,
                    session,
                    tenant_id,
                    document_id,
                    "UNSUPPORTED",
                    f"no parser route for mime type: {mime_type}",
                )

            try:
                parser = parser_registry.for_mime_type(mime_type)
            except UnsupportedMimeTypeError as exc:
                # Defensive backstop only: ParserPolicy said a route exists
                # for this mime type, but ParserRegistry disagrees -- that's
                # config/code drift between config/policies/parser.yaml and
                # the parsers' own SUPPORTED_MIME_TYPES sets, not a normal
                # "unknown format" case (already handled above).
                return _mark_terminal(
                    document_repo, session, tenant_id, document_id, "UNSUPPORTED", str(exc)
                )

            parsed = parser.parse(
                tmp_path, mime_type, tenant_id=tenant_id, document_id=document_id
            )
    except Exception as exc:
        return _mark_terminal(
            document_repo, session, tenant_id, document_id, "FAILED_PARSE", str(exc)
        )

    return process_parsed_document(
        session, language_detector, tenant_id, document_id, mime_type, source_uri, parsed
    )


async def parse_document(
    ctx: dict[str, Any],
    tenant_id: str,
    document_id: str,
    bucket: str,
    key: str,
    mime_type: str,
) -> str:
    session_factory = ctx["session_factory"]
    with session_factory() as session:
        document = process_document(
            session,
            ctx["s3_client"],
            ctx["parser_registry"],
            ctx["language_detector"],
            tenant_id,
            document_id,
            bucket,
            key,
            mime_type,
        )

    if document.status == "PARSED":
        from core.model_registry import get_default_embedding_model
        from embedding.queue import enqueue_embed_job

        model = get_default_embedding_model()
        await enqueue_embed_job(
            ctx["redis"], tenant_id, document_id, model["id"], model["version"]
        )

    return document.status


async def on_startup(ctx: dict[str, Any]) -> None:
    engine = get_engine()
    ctx["session_factory"] = get_sessionmaker(engine)
    ctx["s3_client"] = get_s3_client()
    ctx["parser_registry"] = ParserRegistry(stt_model_size="tiny")
    ctx["language_detector"] = LanguageDetector()


class WorkerSettings:
    functions = [parse_document]
    on_startup = on_startup
    redis_settings: RedisSettings = get_redis_settings()
