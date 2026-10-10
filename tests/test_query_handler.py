"""Offline tests: a fake LLM covers every row of the plan's I/O matrix via graph.invoke."""

from __future__ import annotations

import socket

import httpx
import openai
import pytest
from langchain_core.exceptions import OutputParserException
from langchain_openai.chat_models.base import OpenAIRefusalError
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from content_agent import llm
from content_agent.graph import build_graph, graph
from content_agent.router import EMPTY_REQUEST_MESSAGE, RouteDecision


class _Structured:
    def __init__(self, fake: "FakeLLM", schema):
        self.fake, self.schema = fake, schema

    def invoke(self, prompt):
        self.fake.calls.append((self.schema.__name__, prompt))
        if self.fake.error is not None:
            raise self.fake.error
        return self.fake.responses[self.schema]


class FakeLLM:
    def __init__(self, responses: dict | None = None, error: Exception | None = None):
        self.responses = responses or {}
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def with_structured_output(self, schema):
        return _Structured(self, schema)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def guard(*args, **kwargs):
        raise AssertionError("tests must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture
def use_llm(monkeypatch):
    def install(fake: FakeLLM) -> FakeLLM:
        monkeypatch.setattr(llm, "get_llm", lambda *a, **k: fake)
        return fake

    return install


def _decision(use_llm, intent: str, topic: str) -> FakeLLM:
    return use_llm(FakeLLM({RouteDecision: RouteDecision(intent=intent, topic=topic)}))


def _http_error(cls, status: int, secret: str):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return cls(f"Incorrect API key provided: {secret}", response=response, body=None)


@pytest.mark.parametrize(
    ("request_text", "intent", "topic"),
    [
        ("Give me an overview of AI in B2B marketing", "research", "AI in B2B marketing"),
        ("Write a blog post about remote work tools", "blog", "remote work tools"),
        ("LinkedIn post on our product launch", "linkedin", "our product launch"),
        ("Make an image of a sunrise over a city", "image", "sunrise over a city"),
    ],
)
def test_classified_requests(use_llm, request_text, intent, topic):
    fake = _decision(use_llm, intent, topic)

    result = graph.invoke({"request": request_text})

    assert result["intent"] == intent
    assert result["topic"] == topic
    assert f"**Intent:** {intent}" in result["final_output"]
    assert f"**Topic:** {topic}" in result["final_output"]
    assert result["errors"] == []
    assert len(fake.calls) == 1
    assert request_text in fake.calls[0][1]


def test_blog_success_ending_matches_design(use_llm):
    _decision(use_llm, "blog", "remote work tools")

    result = graph.invoke({"request": "Write a blog post about remote work tools"})

    assert result["final_output"] == (
        "**Intent:** blog\n**Topic:** remote work tools\n\n"
        "The blog writer is not built yet; this run stops after classification."
    )


@pytest.mark.parametrize("request_text", ["", "   "])
def test_empty_request_skips_llm(monkeypatch, request_text):
    def boom(*a, **k):
        raise AssertionError("LLM must not be called for an empty request")

    monkeypatch.setattr(llm, "get_llm", boom)

    result = graph.invoke({"request": request_text})

    assert result["intent"] == "empty"
    assert result["topic"] == ""
    assert result["final_output"] == EMPTY_REQUEST_MESSAGE
    assert result["errors"] == []


SECRET = "sk-test-SECRET-123"


def _validation_error() -> ValidationError:
    try:
        RouteDecision.model_validate({"intent": SECRET, "topic": 1})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected ValidationError")


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (_http_error(openai.AuthenticationError, 401, SECRET), "AuthenticationError"),
        (_http_error(openai.RateLimitError, 429, SECRET), "RateLimitError"),
        (openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")), "APIConnectionError"),
        (OutputParserException(f"bad json {SECRET}"), "OutputParserException"),
        (_validation_error(), "ValidationError"),
        (OpenAIRefusalError(f"refused {SECRET}"), "OpenAIRefusalError"),
    ],
)
def test_llm_failure_is_caught(use_llm, error, kind):
    use_llm(FakeLLM(error=error))

    result = graph.invoke({"request": "Write a blog post about remote work tools"})

    assert result["intent"] == "error"
    assert result["topic"] == ""
    assert kind in result["final_output"]
    assert result["errors"] == [f"query_handler: {kind}"]
    if kind == "AuthenticationError":
        assert "OPENAI_API_KEY" in result["final_output"]
    else:
        assert "OPENAI_API_KEY" not in result["final_output"]
    assert SECRET not in result["final_output"]
    assert all(SECRET not in e for e in result["errors"])


def test_missing_api_key_is_caught(monkeypatch):
    # Real get_llm(): with no key, ChatOpenAI raises OpenAIError at construction.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = graph.invoke({"request": "Write a blog post about remote work tools"})

    assert result["intent"] == "error"
    assert "OPENAI_API_KEY" in result["final_output"]
    assert result["errors"] == ["query_handler: OpenAIError"]


def test_thread_reuse_has_no_stale_errors(use_llm):
    threaded = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    use_llm(FakeLLM(error=_http_error(openai.AuthenticationError, 401, SECRET)))
    first = threaded.invoke({"request": "Write a blog post about remote work tools"}, config)
    assert first["errors"] == ["query_handler: AuthenticationError"]

    _decision(use_llm, "linkedin", "our product launch")
    second = threaded.invoke({"request": "LinkedIn post on our product launch"}, config)

    assert second["errors"] == []
    assert second["intent"] == "linkedin"
    assert second["topic"] == "our product launch"
    assert "AuthenticationError" not in second["final_output"]
