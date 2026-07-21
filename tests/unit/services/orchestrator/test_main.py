from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from orchestrator.main import app


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    # Module-scoped: the real lifespan loads real embedding/reranker/PII
    # models and ensures the Qdrant collections / OpenSearch index exist —
    # amortize that cost across this file's tests rather than repeating it.
    with TestClient(app) as c:
        yield c


def test_health_does_not_require_auth(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_does_not_require_auth(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
