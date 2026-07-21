import uuid
from typing import Any

from core.interfaces import Tool
from core.models import AgentStep, AgentTrace


class ToolNotFoundError(ValueError):
    pass


class MaxIterationsExceededError(RuntimeError):
    pass


class TraceCompletedError(RuntimeError):
    pass


class StepNotPendingApprovalError(RuntimeError):
    pass


class ToolRuntime:
    """Executes AgentStep/AgentTrace records (Plan v2 §A.11) against a
    registry of Tool ABC implementations. Deliberately narrow: this runtime
    executes ONE caller-chosen tool call at a time — it does not itself
    decide which tool to call next (that's an LLM-driven planning loop,
    out of scope for this phase per the plan; pipeline.py drives calls to
    execute_step). What it DOES own: the human-approval halt/resume gate
    and the max_iterations cap, since both are trace-integrity concerns
    independent of who's choosing the tools.
    """

    def __init__(self, tools: dict[str, Tool]) -> None:
        self._tools = tools

    def execute_step(
        self,
        trace: AgentTrace,
        tool_name: str,
        input: dict[str, Any],
        principals: list[str],
    ) -> AgentStep:
        if trace.completed:
            raise TraceCompletedError(f"trace {trace.id} is already completed")
        if len(trace.steps) >= trace.max_iterations:
            raise MaxIterationsExceededError(
                f"trace {trace.id} already has {len(trace.steps)} steps "
                f"(max_iterations={trace.max_iterations})"
            )

        tool = self._tools.get(tool_name)
        if tool is None:
            raise ToolNotFoundError(f"no tool registered named {tool_name!r}")

        step = AgentStep(
            id=str(uuid.uuid4()),
            tenant_id=trace.tenant_id,
            tool_name=tool_name,
            input=input,
            requires_approval=tool.requires_approval,
        )

        if tool.requires_approval:
            # Halt state: append the pending step but do not run the tool.
            # approved_by stays None until a separate resume_step call.
            trace.steps.append(step)
            return step

        step.output = tool.run(principals, **input)
        trace.steps.append(step)
        return step

    def resume_step(
        self,
        trace: AgentTrace,
        step_id: str,
        approved_by: str,
        principals: list[str],
    ) -> AgentStep:
        step = next((s for s in trace.steps if s.id == step_id), None)
        if step is None:
            raise ToolNotFoundError(f"no step {step_id!r} in trace {trace.id}")
        if not step.requires_approval or step.approved_by is not None:
            raise StepNotPendingApprovalError(
                f"step {step_id!r} is not awaiting approval"
            )

        tool = self._tools.get(step.tool_name)
        if tool is None:
            raise ToolNotFoundError(f"no tool registered named {step.tool_name!r}")

        step.approved_by = approved_by
        step.output = tool.run(principals, **step.input)
        return step
