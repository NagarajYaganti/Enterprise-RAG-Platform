import base64
import json
from collections.abc import Generator

import pytest
from connectors.postgres.orm import Base
from connectors.postgres.repository import ChatSessionRepository
from connectors.postgres.session import get_engine, get_sessionmaker
from fastapi.testclient import TestClient
from retrieval.main import app
from sqlalchemy.orm import Session

DATABASE_URL = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"


def _make_token(tenant_id: str) -> str:
    raw = json.dumps({"tenant_id": tenant_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    # Module-scoped: the real lifespan loads real embedding/reranker models —
    # amortize that cost across this file's tests, same as test_main.py.
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = get_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    factory = get_sessionmaker(engine)
    sess = factory()
    for table in reversed(Base.metadata.sorted_tables):
        sess.execute(table.delete())
    sess.commit()
    yield sess
    sess.close()


def test_retrieve_without_auth_is_rejected(client: TestClient) -> None:
    response = client.post("/v1/retrieve", json={"text": "hello", "session_id": "s-1"})

    assert response.status_code == 401


def test_retrieve_with_no_matching_chunks_returns_empty_chunks(
    client: TestClient, session: Session
) -> None:
    token = _make_token("tenant-api-test")

    response = client.post(
        "/v1/retrieve",
        json={"text": "what is the deadline?", "session_id": "s-1", "user_id": "user-1"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["chunks"] == []
    # No OPENAI_API_KEY configured in this test environment -> heuristic
    # pass-through, rewritten query is the original text unchanged.
    assert body["rewritten_query"] == "what is the deadline?"
    assert "query_id" in body


def test_retrieve_response_includes_all_expected_fields(
    client: TestClient, session: Session
) -> None:
    token = _make_token("tenant-api-test")

    response = client.post(
        "/v1/retrieve",
        json={"text": "hello", "session_id": "s-1"},
        headers={"Authorization": f"Bearer {token}"},
    )

    body = response.json()
    assert set(body.keys()) == {"query_id", "rewritten_query", "chunks"}


def test_retrieve_persists_the_turn_for_future_conversation_memory(
    client: TestClient, session: Session
) -> None:
    token = _make_token("tenant-api-test")

    response = client.post(
        "/v1/retrieve",
        json={"text": "what is the loan review deadline?", "session_id": "s-mem", "user_id": "u-1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    history = ChatSessionRepository(session).get_history("tenant-api-test", "u-1", "s-mem")
    assert len(history) == 1
    assert history[0].role == "user"
    assert history[0].text == "what is the loan review deadline?"


def test_retrieve_accepts_filters_without_erroring(client: TestClient, session: Session) -> None:
    token = _make_token("tenant-api-test")

    response = client.post(
        "/v1/retrieve",
        json={
            "text": "hello",
            "session_id": "s-1",
            "filters": {"doc_type": "policy", "department": "lending", "language": "en"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
