import pytest
from core.interfaces import Tool
from core.models import AgentTrace
from orchestrator.agent.tool_runtime import (
    MaxIterationsExceededError,
    StepNotPendingApprovalError,
    ToolNotFoundError,
    ToolRuntime,
    TraceCompletedError,
)

TENANT_ID = "tenant-acme"


class EchoTool(Tool):
    name = "echo"

    def run(self, principals: list[str], **kwargs: object) -> dict[str, object]:
        return {"principals": principals, **kwargs}


class SendEmailTool(Tool):
    name = "send_email"
    requires_approval = True

    def __init__(self) -> None:
        self.call_count = 0

    def run(self, principals: list[str], **kwargs: object) -> str:
        self.call_count += 1
        return f"sent to {kwargs.get('to')}"


def _trace(max_iterations: int = 5) -> AgentTrace:
    return AgentTrace(
        id="trace-1", tenant_id=TENANT_ID, query_id="query-1", max_iterations=max_iterations
    )


def test_execute_step_runs_tool_immediately_when_no_approval_required() -> None:
    runtime = ToolRuntime({"echo": EchoTool()})
    trace = _trace()

    step = runtime.execute_step(trace, "echo", {"text": "hi"}, principals=["p1"])

    assert step.output == {"principals": ["p1"], "text": "hi"}
    assert step.requires_approval is False
    assert step.approved_by is None
    assert trace.steps == [step]


def test_execute_step_halts_before_running_a_tool_that_requires_approval() -> None:
    send_email = SendEmailTool()
    runtime = ToolRuntime({"send_email": send_email})
    trace = _trace()

    step = runtime.execute_step(trace, "send_email", {"to": "a@b.com"}, principals=["p1"])

    assert step.requires_approval is True
    assert step.approved_by is None
    assert step.output is None
    assert send_email.call_count == 0
    assert trace.steps == [step]


def test_execute_step_raises_for_unregistered_tool() -> None:
    runtime = ToolRuntime({"echo": EchoTool()})
    trace = _trace()

    with pytest.raises(ToolNotFoundError):
        runtime.execute_step(trace, "nonexistent", {}, principals=["p1"])


def test_execute_step_raises_once_max_iterations_reached() -> None:
    runtime = ToolRuntime({"echo": EchoTool()})
    trace = _trace(max_iterations=1)
    runtime.execute_step(trace, "echo", {}, principals=["p1"])

    with pytest.raises(MaxIterationsExceededError):
        runtime.execute_step(trace, "echo", {}, principals=["p1"])


def test_execute_step_raises_on_a_completed_trace() -> None:
    runtime = ToolRuntime({"echo": EchoTool()})
    trace = _trace()
    trace.completed = True

    with pytest.raises(TraceCompletedError):
        runtime.execute_step(trace, "echo", {}, principals=["p1"])


def test_resume_step_runs_the_tool_and_records_who_approved_it() -> None:
    send_email = SendEmailTool()
    runtime = ToolRuntime({"send_email": send_email})
    trace = _trace()
    pending = runtime.execute_step(trace, "send_email", {"to": "a@b.com"}, principals=["p1"])

    resumed = runtime.resume_step(trace, pending.id, approved_by="admin-1", principals=["p1"])

    assert resumed is pending  # same step object, mutated in place
    assert resumed.approved_by == "admin-1"
    assert resumed.output == "sent to a@b.com"
    assert send_email.call_count == 1


def test_resume_step_raises_if_step_does_not_require_approval() -> None:
    runtime = ToolRuntime({"echo": EchoTool()})
    trace = _trace()
    step = runtime.execute_step(trace, "echo", {"text": "hi"}, principals=["p1"])

    with pytest.raises(StepNotPendingApprovalError):
        runtime.resume_step(trace, step.id, approved_by="admin-1", principals=["p1"])


def test_resume_step_raises_if_already_approved() -> None:
    runtime = ToolRuntime({"send_email": SendEmailTool()})
    trace = _trace()
    pending = runtime.execute_step(trace, "send_email", {"to": "a@b.com"}, principals=["p1"])
    runtime.resume_step(trace, pending.id, approved_by="admin-1", principals=["p1"])

    with pytest.raises(StepNotPendingApprovalError):
        runtime.resume_step(trace, pending.id, approved_by="admin-2", principals=["p1"])


def test_resume_step_raises_for_unknown_step_id() -> None:
    runtime = ToolRuntime({"send_email": SendEmailTool()})
    trace = _trace()

    with pytest.raises(ToolNotFoundError):
        runtime.resume_step(trace, "nonexistent-step", approved_by="admin-1", principals=["p1"])
