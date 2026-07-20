from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DocumentORM(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    source_uri: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    checksum: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    acl_principals: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ChunkORM(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    acl_principals: Mapped[list[str]] = mapped_column(JSON, default=list)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    doc_type: Mapped[str | None] = mapped_column(String, nullable=True)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[str | None] = mapped_column(String, nullable=True)


class ChatTurnORM(Base):
    """Phase-3 addition: one row per conversation turn, not a JSON blob —
    mirrors the Chunk/Document per-row pattern for queryability/audit.
    ChatSession is keyed by tenant + user + session (no separate "session"
    row is needed; the triple identifies a session implicitly via its
    turns' shared session_id).
    """

    __tablename__ = "chat_turns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class EntityORM(Base):
    """Phase-3 addition (GraphRAG, optional/flagged-off). Storage lives in
    Postgres, not a graph database — docs/ARCHITECTURE.md's fixed local dev
    stack has none, and adding one would redesign that fixed contract
    without authorization.
    """

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    chunk_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)


class RelationORM(Base):
    __tablename__ = "relations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    subject_entity_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    predicate: Mapped[str] = mapped_column(String, nullable=False)
    object_entity_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    chunk_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
