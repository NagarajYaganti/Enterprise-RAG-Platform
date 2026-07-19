import base64
import binascii
import json
from contextvars import ContextVar

_tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)


def get_current_tenant_id() -> str | None:
    return _tenant_id_var.get()


def set_current_tenant_id(tenant_id: str | None) -> None:
    _tenant_id_var.set(tenant_id)


def decode_stub_token(token: str) -> str | None:
    """INSECURE STUB — decodes an unsigned base64url JSON payload of the form
    {"tenant_id": "..."}. No signature verification. Replaced by real OIDC
    token validation in Phase 5.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    tenant_id = payload.get("tenant_id")
    return tenant_id if isinstance(tenant_id, str) else None
