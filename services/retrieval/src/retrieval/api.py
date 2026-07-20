import uuid
from collections.abc import Generator
from datetime import datetime, timezone

from connectors.postgres.repository import ChatSessionRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.models import ChatTurn, Query, RetrievalFilters
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from retrieval.pipeline import retrieve

router = APIRouter(prefix="/v1")

_engine = get_engine()
_session_factory = get_sessionmaker(_engine)


def get_db_session() -> Generator[Session, None, None]:
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def _require_tenant_id(request: Request) -> str:
    # tenant_id comes ONLY from request.state (set by TenantContextMiddleware
    # from the auth token), never from the request body — an explicit
    # security rule, matching the pattern already used in ingestion/api.py.
    tenant_id: str | None = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="missing tenant context")
    return tenant_id


class RetrievalFilterRequest(BaseModel):
    language: str | None = None
    doc_type: str | None = None
    department: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class RetrieveRequest(BaseModel):
    text: str
    session_id: str
    user_id: str = ""
    top_k: int = 10
    filters: RetrievalFilterRequest = Field(default_factory=RetrievalFilterRequest)
    principals: list[str] = Field(default_factory=list)


class ScoredChunkResponse(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    score: float


class RetrieveResponse(BaseModel):
    query_id: str
    rewritten_query: str
    chunks: list[ScoredChunkResponse]


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve_endpoint(
    request: Request,
    body: RetrieveRequest,
    session: Session = Depends(get_db_session),
) -> RetrieveResponse:
    tenant_id = _require_tenant_id(request)

    deps = request.app.state.retrieval_dependencies
    settings = request.app.state.retrieval_settings

    query = Query(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        session_id=body.session_id,
        text=body.text,
        user_id=body.user_id,
    )
    filters = RetrievalFilters(**body.filters.model_dump())

    chat_repo = ChatSessionRepository(session)
    history = chat_repo.get_history(tenant_id, body.user_id, body.session_id)

    outcome = retrieve(
        session, deps, query, body.principals, filters, settings, history, body.top_k
    )

    # Record this turn for future conversation memory — appended AFTER
    # retrieval so it doesn't influence the rewrite of its own turn.
    chat_repo.append_turn(
        ChatTurn(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=body.user_id,
            session_id=body.session_id,
            role="user",
            text=body.text,
            created_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    return RetrieveResponse(
        query_id=outcome.result.query_id,
        rewritten_query=outcome.rewritten_query,
        chunks=[
            ScoredChunkResponse(
                chunk_id=scored_chunk.chunk.id,
                document_id=scored_chunk.chunk.document_id,
                text=scored_chunk.chunk.text,
                score=scored_chunk.score,
            )
            for scored_chunk in outcome.result.chunks
        ],
    )
