from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.tenant_context import decode_stub_token, set_current_tenant_id

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]

EXEMPT_PATHS = frozenset({"/health", "/metrics"})


class TenantContextMiddleware(BaseHTTPMiddleware):
    """INSECURE STUB — extracts tenant_id from an unsigned bearer token.
    No signature verification. Replaced by real OIDC/JWT validation in Phase 5.

    Shared across services (relocated here from services/gateway in Phase 1
    so services/ingestion can reuse it without duplicating the stub).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return Response(content="missing bearer token", status_code=401)

        token = auth_header.split(" ", 1)[1]
        tenant_id = decode_stub_token(token)
        if tenant_id is None:
            return Response(content="invalid token", status_code=401)

        request.state.tenant_id = tenant_id
        set_current_tenant_id(tenant_id)
        try:
            response = await call_next(request)
        finally:
            set_current_tenant_id(None)
        return response
