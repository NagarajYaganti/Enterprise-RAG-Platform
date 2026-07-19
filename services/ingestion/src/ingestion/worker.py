import tempfile
from pathlib import Path
from typing import Any

from arq.connections import RedisSettings
from connectors.parser_registry import ParserRegistry
from connectors.postgres.repository import ChunkRepository, DocumentRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.models import Document
from preprocessing.chunkers.structure_aware import StructureAwareChunker
from preprocessing.language_detect import LanguageDetector
from preprocessing.pipeline import run_pipeline
from preprocessing.translator_stub import StubTranslator
from sqlalchemy.orm import Session

from ingestion.dedupe import determine_version
from ingestion.queue import get_redis_settings
from ingestion.storage import download_fileobj, get_s3_client

DEFAULT_CHUNK_STRATEGY = "structure_aware"


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
) -> Document:
    """Core ingestion pipeline: download -> dedupe check -> parse ->
    preprocess -> persist. Kept independent of arq's ctx mechanism so it can
    be called directly in tests without a live worker process.
    """
    document_repo = DocumentRepository(session)
    chunk_repo = ChunkRepository(session)
    source_uri = f"s3://{bucket}/{key}"

    with tempfile.NamedTemporaryFile(suffix=Path(key).suffix) as tmp:
        download_fileobj(s3_client, bucket, key, tmp)
        tmp.flush()
        parser = parser_registry.for_mime_type(mime_type)
        parsed = parser.parse(
            Path(tmp.name), mime_type, tenant_id=tenant_id, document_id=document_id
        )

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
        chunker = StructureAwareChunker()
        chunks = run_pipeline(
            parsed,
            chunker,
            DEFAULT_CHUNK_STRATEGY,
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
