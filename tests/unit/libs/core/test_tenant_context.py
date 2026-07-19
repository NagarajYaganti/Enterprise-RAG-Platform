import base64
import json

from core.tenant_context import (
    decode_stub_token,
    get_current_tenant_id,
    set_current_tenant_id,
)


def _make_token(payload: dict[str, object]) -> str:
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_decode_stub_token_extracts_tenant_id() -> None:
    token = _make_token({"tenant_id": "tenant-acme"})
    assert decode_stub_token(token) == "tenant-acme"


def test_decode_stub_token_rejects_garbage() -> None:
    assert decode_stub_token("not-valid-base64!!!") is None


def test_decode_stub_token_rejects_missing_tenant_id() -> None:
    token = _make_token({"other": "value"})
    assert decode_stub_token(token) is None


def test_contextvar_roundtrip() -> None:
    assert get_current_tenant_id() is None
    set_current_tenant_id("tenant-acme")
    assert get_current_tenant_id() == "tenant-acme"
    set_current_tenant_id(None)
