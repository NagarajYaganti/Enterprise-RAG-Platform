import base64
import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from gateway.main import app
from gateway.middleware.tenant_context import TenantContextMiddleware

client = TestClient(app)


def _make_token(payload: dict[str, object]) -> str:
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_health_does_not_require_auth() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_does_not_require_auth() -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def _build_test_app() -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(TenantContextMiddleware)

    @test_app.get("/whoami")
    def whoami(request: Request) -> dict[str, str | None]:
        return {"tenant_id": getattr(request.state, "tenant_id", None)}

    return test_app


def test_request_with_valid_token_sets_tenant_state() -> None:
    test_client = TestClient(_build_test_app())
    token = _make_token({"tenant_id": "tenant-acme"})

    response = test_client.get("/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-acme"}


def test_request_with_invalid_token_is_rejected() -> None:
    test_client = TestClient(_build_test_app())

    response = test_client.get(
        "/whoami", headers={"Authorization": "Bearer not-valid-base64!!!"}
    )

    assert response.status_code == 401


def test_request_missing_bearer_prefix_is_rejected() -> None:
    test_client = TestClient(_build_test_app())

    response = test_client.get("/whoami", headers={"Authorization": "not-a-bearer-token"})

    assert response.status_code == 401


def test_second_tenant_gets_isolated_state() -> None:
    test_client = TestClient(_build_test_app())
    token_a = _make_token({"tenant_id": "tenant-a"})
    token_b = _make_token({"tenant_id": "tenant-b"})

    response_a = test_client.get("/whoami", headers={"Authorization": f"Bearer {token_a}"})
    response_b = test_client.get("/whoami", headers={"Authorization": f"Bearer {token_b}"})

    assert response_a.json() == {"tenant_id": "tenant-a"}
    assert response_b.json() == {"tenant_id": "tenant-b"}
