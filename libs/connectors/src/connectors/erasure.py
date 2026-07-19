from collections.abc import Callable
from dataclasses import dataclass, field

CleanupHook = Callable[[str, str], None]


@dataclass
class ErasureFailure:
    hook_name: str
    error: str


class ErasureError(Exception):
    def __init__(self, failures: list[ErasureFailure]) -> None:
        self.failures = failures
        super().__init__(
            f"{len(failures)} cleanup hook(s) failed: "
            + ", ".join(f"{f.hook_name}: {f.error}" for f in failures)
        )


@dataclass
class ErasureResult:
    tenant_id: str
    document_id: str
    completed_hooks: list[str] = field(default_factory=list)


class ErasureService:
    """Hard-delete orchestrator: chunks, vectors, and keyword-index entries
    in one API — the erasure/GDPR foundation.

    Extensible by design (ASSUMPTION, see Plan v2 §5): no cache exists yet
    in this system, so no cache-cleanup hook is registered today. Adding
    one later (e.g. Phase 4's semantic cache) is a single register() call,
    not a redesign of this API.
    """

    def __init__(self) -> None:
        self._hooks: list[tuple[str, CleanupHook]] = []

    def register(self, name: str, hook: CleanupHook) -> None:
        self._hooks.append((name, hook))

    def erase_document(self, tenant_id: str, document_id: str) -> ErasureResult:
        completed: list[str] = []
        failures: list[ErasureFailure] = []

        for name, hook in self._hooks:
            try:
                hook(tenant_id, document_id)
                completed.append(name)
            except Exception as exc:  # noqa: BLE001 - intentionally broad: one
                # failing hook must not stop the others from running, and
                # every failure is collected and reported, not swallowed.
                failures.append(ErasureFailure(hook_name=name, error=str(exc)))

        if failures:
            raise ErasureError(failures)

        return ErasureResult(
            tenant_id=tenant_id, document_id=document_id, completed_hooks=completed
        )
