from typing import Any, cast

from core.models import ChatTurn, Chunk, Document
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from connectors.postgres.orm import ChatTurnORM, ChunkORM, DocumentORM


def _document_to_model(row: DocumentORM) -> Document:
    return Document(
        id=row.id,
        tenant_id=row.tenant_id,
        source_uri=row.source_uri,
        mime_type=row.mime_type,
        checksum=row.checksum,
        version=row.version,
        status=row.status,  # type: ignore[arg-type]
        acl_principals=list(row.acl_principals),
    )


def _chat_turn_to_model(row: ChatTurnORM) -> ChatTurn:
    return ChatTurn(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        session_id=row.session_id,
        role=row.role,  # type: ignore[arg-type]
        text=row.text,
        created_at=row.created_at,
    )


def _chunk_to_model(row: ChunkORM) -> Chunk:
    return Chunk(
        id=row.id,
        tenant_id=row.tenant_id,
        document_id=row.document_id,
        text=row.text,
        position=row.position,
        language=row.language,
        version=row.version,
        status=row.status,  # type: ignore[arg-type]
        acl_principals=list(row.acl_principals),
        metadata=dict(row.chunk_metadata),
        doc_type=row.doc_type,
        department=row.department,
        date=row.date,
    )


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, document: Document) -> Document:
        row = self._session.get(DocumentORM, document.id)
        if row is None:
            row = DocumentORM(id=document.id, tenant_id=document.tenant_id)
            self._session.add(row)
        row.source_uri = document.source_uri
        row.mime_type = document.mime_type
        row.checksum = document.checksum
        row.version = document.version
        row.status = document.status
        row.acl_principals = list(document.acl_principals)
        self._session.flush()
        return _document_to_model(row)

    def get(self, tenant_id: str, document_id: str) -> Document | None:
        row = self._session.get(DocumentORM, document_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return _document_to_model(row)

    def find_by_checksum(self, tenant_id: str, checksum: str) -> Document | None:
        stmt = select(DocumentORM).where(
            DocumentORM.tenant_id == tenant_id, DocumentORM.checksum == checksum
        )
        row = self._session.execute(stmt).scalars().first()
        return _document_to_model(row) if row else None

    def find_by_source_uri(self, tenant_id: str, source_uri: str) -> Document | None:
        stmt = select(DocumentORM).where(
            DocumentORM.tenant_id == tenant_id, DocumentORM.source_uri == source_uri
        )
        row = self._session.execute(stmt).scalars().first()
        return _document_to_model(row) if row else None

    def list_for_tenant(self, tenant_id: str) -> list[Document]:
        stmt = select(DocumentORM).where(DocumentORM.tenant_id == tenant_id)
        rows = self._session.execute(stmt).scalars().all()
        return [_document_to_model(row) for row in rows]

    def hard_delete(self, tenant_id: str, document_id: str) -> None:
        """Real SQL DELETE, not a status flip — the erasure/GDPR path.
        Tenant-scoped: a document_id belonging to another tenant is a no-op.
        """
        stmt = delete(DocumentORM).where(
            DocumentORM.tenant_id == tenant_id, DocumentORM.id == document_id
        )
        self._session.execute(stmt)
        self._session.flush()


class ChunkRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def bulk_insert(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            row = ChunkORM(
                id=chunk.id,
                tenant_id=chunk.tenant_id,
                document_id=chunk.document_id,
                text=chunk.text,
                position=chunk.position,
                language=chunk.language,
                version=chunk.version,
                status=chunk.status,
                acl_principals=list(chunk.acl_principals),
                chunk_metadata=dict(chunk.metadata),
                doc_type=chunk.doc_type,
                department=chunk.department,
                date=chunk.date,
            )
            self._session.add(row)
        self._session.flush()

    def list_for_document(
        self, tenant_id: str, document_id: str, *, active_only: bool = True
    ) -> list[Chunk]:
        stmt = select(ChunkORM).where(
            ChunkORM.tenant_id == tenant_id, ChunkORM.document_id == document_id
        )
        if active_only:
            stmt = stmt.where(ChunkORM.status == "active")
        rows = self._session.execute(stmt).scalars().all()
        return [_chunk_to_model(row) for row in rows]

    def get_by_ids(self, tenant_id: str, chunk_ids: list[str]) -> list[Chunk]:
        """Phase-3 addition: retrieval hydrates full Chunk objects (text,
        metadata) from a fused ranked list of chunk_ids before reranking —
        tenant-scoped like every other query here, so a chunk_id belonging
        to another tenant is silently excluded, not just filtered client-side.
        """
        if not chunk_ids:
            return []
        stmt = select(ChunkORM).where(
            ChunkORM.tenant_id == tenant_id, ChunkORM.id.in_(chunk_ids)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_chunk_to_model(row) for row in rows]

    def supersede_for_document(self, tenant_id: str, document_id: str) -> int:
        stmt = select(ChunkORM).where(
            ChunkORM.tenant_id == tenant_id,
            ChunkORM.document_id == document_id,
            ChunkORM.status == "active",
        )
        rows = self._session.execute(stmt).scalars().all()
        for row in rows:
            row.status = "superseded"
        self._session.flush()
        return len(rows)

    def list_for_tenant(self, tenant_id: str) -> list[Chunk]:
        stmt = select(ChunkORM).where(ChunkORM.tenant_id == tenant_id)
        rows = self._session.execute(stmt).scalars().all()
        return [_chunk_to_model(row) for row in rows]

    def hard_delete_for_document(self, tenant_id: str, document_id: str) -> int:
        """Real SQL DELETE of every chunk (active or superseded) for a
        document — the erasure/GDPR path, distinct from supersede_for_document
        which only flips status. Returns the number of rows deleted.
        """
        stmt = delete(ChunkORM).where(
            ChunkORM.tenant_id == tenant_id, ChunkORM.document_id == document_id
        )
        result = cast("CursorResult[Any]", self._session.execute(stmt))
        self._session.flush()
        return result.rowcount


class ChatSessionRepository:
    """Phase-3 addition: ChatSession keyed by tenant + user + session (per
    Section 4 Phase 3 task text). tenant_id is always a mandatory filter,
    matching the "impossible to query without tenant_id" pattern from every
    other repository in this file.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def append_turn(self, turn: ChatTurn) -> ChatTurn:
        row = ChatTurnORM(
            id=turn.id,
            tenant_id=turn.tenant_id,
            user_id=turn.user_id,
            session_id=turn.session_id,
            role=turn.role,
            text=turn.text,
            created_at=turn.created_at,
        )
        self._session.add(row)
        self._session.flush()
        return _chat_turn_to_model(row)

    def get_history(
        self, tenant_id: str, user_id: str, session_id: str, *, limit: int = 20
    ) -> list[ChatTurn]:
        stmt = (
            select(ChatTurnORM)
            .where(
                ChatTurnORM.tenant_id == tenant_id,
                ChatTurnORM.user_id == user_id,
                ChatTurnORM.session_id == session_id,
            )
            .order_by(ChatTurnORM.created_at)
            .limit(limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_chat_turn_to_model(row) for row in rows]
