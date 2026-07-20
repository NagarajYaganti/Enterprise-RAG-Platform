from datetime import datetime, timezone
from typing import Any

from core.interfaces import LLMProvider
from core.models import ChatTurn, Completion
from retrieval.query_understanding import decompose_query, rewrite_query


class FakeLLMProvider(LLMProvider):
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.calls: list[tuple[list[dict[str, str]], str, dict[str, Any]]] = []

    def generate(
        self, messages: list[Any], model_id: str, params: dict[str, Any]
    ) -> Completion:
        self.calls.append((messages, model_id, params))
        return Completion(
            tenant_id=params["tenant_id"], model_id=model_id, text=self._response_text
        )


def _turn(role: str, text: str) -> ChatTurn:
    return ChatTurn(
        id="turn-1",
        tenant_id="tenant-acme",
        user_id="user-1",
        session_id="session-1",
        role=role,  # type: ignore[arg-type]
        text=text,
        created_at=datetime.now(timezone.utc),
    )


def test_rewrite_query_falls_back_unchanged_when_no_llm_provider() -> None:
    history = [_turn("user", "what is the loan review deadline?")]

    result = rewrite_query("what about it?", history, None, "gpt-5.6-luna", "tenant-acme")

    assert result == "what about it?"


def test_rewrite_query_falls_back_unchanged_when_no_history() -> None:
    llm = FakeLLMProvider("should not be used")

    result = rewrite_query("what about it?", [], llm, "gpt-5.6-luna", "tenant-acme")

    assert result == "what about it?"
    assert llm.calls == []


def test_rewrite_query_uses_llm_when_provider_and_history_present() -> None:
    llm = FakeLLMProvider("What is the loan review deadline?")
    history = [_turn("user", "tell me about the loan review policy")]

    result = rewrite_query("what about it?", history, llm, "gpt-5.6-luna", "tenant-acme")

    assert result == "What is the loan review deadline?"
    assert len(llm.calls) == 1
    messages, model_id, params = llm.calls[0]
    assert model_id == "gpt-5.6-luna"
    assert params["tenant_id"] == "tenant-acme"
    assert "what about it?" in messages[-1]["content"]


def test_decompose_query_falls_back_to_single_item_list_when_no_llm_provider() -> None:
    result = decompose_query("a and b", None, "gpt-5.6-luna", "tenant-acme")

    assert result == ["a and b"]


def test_decompose_query_splits_on_newlines_from_llm_response() -> None:
    llm = FakeLLMProvider("What is the deadline?\nWho approves it?")

    result = decompose_query(
        "What is the deadline and who approves it?", llm, "gpt-5.6-luna", "tenant-acme"
    )

    assert result == ["What is the deadline?", "Who approves it?"]


def test_decompose_query_returns_single_item_when_llm_response_is_one_line() -> None:
    llm = FakeLLMProvider("What is the deadline?")

    result = decompose_query("What is the deadline?", llm, "gpt-5.6-luna", "tenant-acme")

    assert result == ["What is the deadline?"]
