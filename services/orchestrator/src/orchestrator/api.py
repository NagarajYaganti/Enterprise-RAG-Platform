import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

from connectors.postgres.repository import ChatSessionRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from core.models import AgentTrace, ChatTurn, Query, RetrievalFilters
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from orchestrator.agent.tool_runtime import (
    MaxIterationsExceededError,
    StepNotPendingApprovalError,
    ToolNotFoundError,
    TraceCompletedError,
)
from orchestrator.pipeline import LLMProviderNotConfiguredError, orchestrate
from orchestrator.settings import OrchestratorSettings

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
    # Same rule as retrieval/ingestion's APIs: tenant_id comes ONLY from
    # request.state (set by TenantContextMiddleware), never from the body.
    tenant_id: str | None = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="missing tenant context")
    return tenant_id


class GenerateFilterRequest(BaseModel):
    language: str | None = None
    doc_type: str | None = None
    department: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class GenerateRequest(BaseModel):
    text: str
    session_id: str
    user_id: str = ""
    top_k: int = 10
    domain: str = "common"
    language: str = "en"
    filters: GenerateFilterRequest = Field(default_factory=GenerateFilterRequest)
    principals: list[str] = Field(default_factory=list)
    budget: float | None = None


class GenerateResponse(BaseModel):
    query_id: str
    rewritten_query: str
    answer_text: str
    cited_chunk_ids: list[str]
    model_id: str | None
    from_cache: bool
    blocked: bool
    blocked_reason: str | None


@router.post("/generate", response_model=GenerateResponse)
def generate_endpoint(
    request: Request,
    body: GenerateRequest,
    session: Session = Depends(get_db_session),
) -> GenerateResponse:
    tenant_id = _require_tenant_id(request)

    deps = request.app.state.orchestration_dependencies
    retrieval_settings = request.app.state.retrieval_settings
    orchestrator_settings: OrchestratorSettings = request.app.state.orchestrator_settings

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

    try:
        result = orchestrate(
            session,
            deps,
            query,
            body.principals,
            filters,
            retrieval_settings,
            orchestrator_settings,
            history,
            body.domain,
            body.language,
            body.top_k,
            body.budget,
        )
    except LLMProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Recorded AFTER orchestrate() so it doesn't influence the rewrite of
    # its own turn, matching retrieval/api.py's ordering. A blocked
    # exchange isn't recorded as an assistant turn — the model never said
    # anything, so it shouldn't shape future pronoun resolution.
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
    if not result.blocked:
        chat_repo.append_turn(
            ChatTurn(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                user_id=body.user_id,
                session_id=body.session_id,
                role="assistant",
                text=result.answer_text,
                created_at=datetime.now(timezone.utc),
            )
        )
    session.commit()

    return GenerateResponse(
        query_id=result.query_id,
        rewritten_query=result.rewritten_query,
        answer_text=result.answer_text,
        cited_chunk_ids=result.cited_chunk_ids,
        model_id=result.model_id,
        from_cache=result.from_cache,
        blocked=result.blocked,
        blocked_reason=result.blocked_reason,
    )


# --- Agentic RAG: permission-scoped tools + human approval gates ---------
# Gated behind agent_mode_enabled (off by default). Traces are kept
# in-memory on app.state for this phase — no AgentTrace/AgentStep
# persistence layer has been built yet (a stated, deferred limitation:
# traces don't survive a process restart). ToolRuntime itself only executes
# ONE caller-chosen tool call at a time; it never decides which tool to
# call next, so there is deliberately no "autonomous loop" endpoint here.


def _require_agent_mode(request: Request) -> None:
    settings: OrchestratorSettings = request.app.state.orchestrator_settings
    if not settings.agent_mode_enabled:
        raise HTTPException(status_code=404, detail="agent mode is not enabled")


class AgentTraceCreateRequest(BaseModel):
    query_id: str
    max_iterations: int = 10


class AgentStepResponse(BaseModel):
    id: str
    tool_name: str
    input: dict[str, Any]
    output: Any | None
    requires_approval: bool
    approved_by: str | None


class AgentTraceResponse(BaseModel):
    id: str
    tenant_id: str
    query_id: str
    steps: list[AgentStepResponse]
    max_iterations: int
    completed: bool


class AgentStepRequest(BaseModel):
    tool_name: str
    input: dict[str, Any] = Field(default_factory=dict)
    principals: list[str] = Field(default_factory=list)


class AgentResumeRequest(BaseModel):
    approved_by: str
    principals: list[str] = Field(default_factory=list)


def _trace_response(trace: Any) -> AgentTraceResponse:
    return AgentTraceResponse(
        id=trace.id,
        tenant_id=trace.tenant_id,
        query_id=trace.query_id,
        steps=[_step_response(s) for s in trace.steps],
        max_iterations=trace.max_iterations,
        completed=trace.completed,
    )


def _step_response(step: Any) -> AgentStepResponse:
    return AgentStepResponse(
        id=step.id,
        tool_name=step.tool_name,
        input=step.input,
        output=step.output,
        requires_approval=step.requires_approval,
        approved_by=step.approved_by,
    )


def _get_owned_trace(request: Request, trace_id: str, tenant_id: str) -> Any:
    trace = request.app.state.agent_traces.get(trace_id)
    if trace is None or trace.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace


@router.post("/agent/traces", response_model=AgentTraceResponse)
def create_trace_endpoint(request: Request, body: AgentTraceCreateRequest) -> AgentTraceResponse:
    tenant_id = _require_tenant_id(request)
    _require_agent_mode(request)

    trace = AgentTrace(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        query_id=body.query_id,
        max_iterations=body.max_iterations,
    )
    request.app.state.agent_traces[trace.id] = trace
    return _trace_response(trace)


@router.get("/agent/traces/{trace_id}", response_model=AgentTraceResponse)
def get_trace_endpoint(trace_id: str, request: Request) -> AgentTraceResponse:
    tenant_id = _require_tenant_id(request)
    _require_agent_mode(request)
    trace = _get_owned_trace(request, trace_id, tenant_id)
    return _trace_response(trace)


@router.post("/agent/traces/{trace_id}/steps", response_model=AgentStepResponse)
def execute_step_endpoint(
    trace_id: str, request: Request, body: AgentStepRequest
) -> AgentStepResponse:
    tenant_id = _require_tenant_id(request)
    _require_agent_mode(request)
    trace = _get_owned_trace(request, trace_id, tenant_id)
    runtime = request.app.state.tool_runtime

    try:
        step = runtime.execute_step(trace, body.tool_name, body.input, body.principals)
    except ToolNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (MaxIterationsExceededError, TraceCompletedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _step_response(step)


@router.post("/agent/traces/{trace_id}/steps/{step_id}/resume", response_model=AgentStepResponse)
def resume_step_endpoint(
    trace_id: str, step_id: str, request: Request, body: AgentResumeRequest
) -> AgentStepResponse:
    tenant_id = _require_tenant_id(request)
    _require_agent_mode(request)
    trace = _get_owned_trace(request, trace_id, tenant_id)
    runtime = request.app.state.tool_runtime

    try:
        step = runtime.resume_step(trace, step_id, body.approved_by, body.principals)
    except (ToolNotFoundError, StepNotPendingApprovalError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _step_response(step)
