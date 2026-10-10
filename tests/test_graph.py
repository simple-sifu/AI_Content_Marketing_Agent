"""Offline tests: fake LLM + mocked SerpAPI cover every row of the plan's I/O matrix."""

from __future__ import annotations

import re
import socket

import pytest

from content_agent import llm, research
from content_agent.graph import graph
from content_agent.research import MISSING_SERPAPI_KEY, QueryPlan, Synthesis
from content_agent.router import EMPTY_REQUEST_MESSAGE, RouteDecision


class _Structured:
    def __init__(self, fake: "FakeLLM", schema):
        self.fake, self.schema = fake, schema

    def invoke(self, prompt):
        self.fake.calls.append((self.schema.__name__, prompt))
        return self.fake.responses[self.schema]


class FakeLLM:
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def with_structured_output(self, schema):
        return _Structured(self, schema)


def _results(prefix: str, n: int = 2) -> list[dict]:
    return [
        {"title": f"{prefix} {i}", "link": f"https://example.com/{prefix}/{i}", "snippet": f"{prefix} snippet {i}"}
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def guard(*args, **kwargs):
        raise AssertionError("tests must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM(
        {
            RouteDecision: RouteDecision(intent="research", topic="AI trends in B2B marketing"),
            QueryPlan: QueryPlan(queries=["q one", "q two", "q three"]),
            Synthesis: Synthesis(
                summary="AI adoption in B2B marketing is rising [1][2].",
                key_findings=[
                    "Personalization at scale is the top use case [1].",
                    "Teams report faster content production [3].",
                    "An uncited claim that must be dropped.",
                    "Bogus citation that must be dropped [99].",
                ],
            ),
        }
    )
    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: fake)
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    return fake


def _citations_map_to_sources(report: str) -> None:
    body, _, sources_section = report.partition("## Sources")
    assert sources_section, "report must have a Sources section"
    listed = dict(re.findall(r"^(\d+)\. \[.*?\]\((https?://\S+)\)", sources_section, re.M))
    cited = set(re.findall(r"\[(\d+)\]", body))
    assert cited, "report must contain citations"
    assert cited <= set(listed), f"citations {cited - set(listed)} have no source URL"


def test_research_request(fake_llm, monkeypatch):
    calls = []

    def search(query, api_key):
        calls.append(query)
        return _results(query.replace(" ", "-"))

    monkeypatch.setattr(research, "serpapi_search", search)
    out = graph.invoke({"request": "Research AI trends in B2B marketing"})

    assert out["intent"] == "research"
    assert calls == ["q one", "q two", "q three"]
    assert len(out["sources"]) == 6
    report = out["final_output"]
    assert report.startswith("# Research Report: AI trends in B2B marketing")
    assert "## Executive Summary" in report and "## Key Findings" in report
    assert "must be dropped" not in report
    assert "[99]" not in report
    _citations_map_to_sources(report)
    assert not out.get("errors")


def test_duplicate_urls_are_deduped(fake_llm, monkeypatch):
    monkeypatch.setattr(research, "serpapi_search", lambda q, k: _results("same", 2))
    out = graph.invoke({"request": "Research AI trends"})
    assert [s["url"] for s in out["sources"]] == [
        "https://example.com/same/0",
        "https://example.com/same/1",
    ]


def test_some_searches_fail(fake_llm, monkeypatch):
    def search(query, api_key):
        if query == "q two":
            raise RuntimeError("Your account has run out of searches.")
        return _results(query.replace(" ", "-"))

    monkeypatch.setattr(research, "serpapi_search", search)
    out = graph.invoke({"request": "Research AI trends in B2B marketing"})

    assert len(out["sources"]) == 4
    assert len(out["errors"]) == 1 and "q two" in out["errors"][0]
    _citations_map_to_sources(out["final_output"])


def test_no_results_at_all(fake_llm, monkeypatch):
    def search(query, api_key):
        if query == "q one":
            raise RuntimeError("quota exceeded")
        return []

    monkeypatch.setattr(research, "serpapi_search", search)
    out = graph.invoke({"request": "Research something obscure"})

    report = out["final_output"]
    assert "No sources were found" in report
    assert not re.search(r"\[\d+\]", report), "no citations may be fabricated"
    assert "## Sources" not in report
    assert "Synthesis" not in [name for name, _ in fake_llm.calls]


def test_missing_serpapi_key(fake_llm, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "")
    monkeypatch.setattr(
        research, "serpapi_search", lambda q, k: pytest.fail("must not search without a key")
    )
    out = graph.invoke({"request": "Research AI trends"})
    assert "SERPAPI_API_KEY" in out["final_output"]
    assert MISSING_SERPAPI_KEY in out["errors"]


@pytest.mark.parametrize("request_text", ["", "   \n\t"])
def test_empty_request(fake_llm, request_text):
    out = graph.invoke({"request": request_text})
    assert out["final_output"] == EMPTY_REQUEST_MESSAGE
    assert fake_llm.calls == [], "empty request must short-circuit before any LLM call"
    assert "sources" not in out


@pytest.mark.parametrize(
    ("intent", "label"),
    [("blog", "SEO blog post"), ("linkedin", "LinkedIn post"), ("image", "image generation")],
)
def test_deferred_formats_return_report_with_note(fake_llm, monkeypatch, intent, label):
    fake_llm.responses[RouteDecision] = RouteDecision(intent=intent, topic="AI trends")
    monkeypatch.setattr(research, "serpapi_search", lambda q, k: _results(q.replace(" ", "-")))
    out = graph.invoke({"request": f"Write a {intent} about AI trends"})
    assert out["target_format"] == "report"
    assert f"{label} output is coming soon" in out["final_output"]
    _citations_map_to_sources(out["final_output"])


def test_serpapi_search_parses_and_reports_errors(monkeypatch):
    import serpapi

    payloads = {
        "ok": {"organic_results": _results("ok", 1)},
        "empty": {"error": "Google hasn't returned any results for this query."},
        "quota": {"error": "Your account has run out of searches."},
    }

    class FakeSearch:
        def __init__(self, params):
            self.params = params

        def get_dict(self):
            return payloads[self.params["q"]]

    monkeypatch.setattr(serpapi, "GoogleSearch", FakeSearch)
    assert research.serpapi_search("ok", "k")[0]["link"] == "https://example.com/ok/0"
    assert research.serpapi_search("empty", "k") == []
    with pytest.raises(RuntimeError, match="run out of searches"):
        research.serpapi_search("quota", "k")


def test_get_llm_reads_model_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-model")
    assert llm.get_llm().model_name == "gpt-test-model"
    monkeypatch.delenv("OPENAI_MODEL")
    assert llm.get_llm().model_name == "gpt-4o-mini"


def test_search_error_redacts_api_key(fake_llm, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "secret-serp-key-123")

    def search(query, api_key):
        if query == "q two":
            raise ConnectionError(
                f"Max retries exceeded with url: /search?q=x&api_key={api_key}&num=5"
            )
        return _results(query.replace(" ", "-"))

    monkeypatch.setattr(research, "serpapi_search", search)
    out = graph.invoke({"request": "Research AI trends"})
    assert "secret-serp-key-123" not in out["final_output"]
    assert "secret-serp-key-123" not in " ".join(out["errors"])
    assert "api_key=***" in out["final_output"]


@pytest.mark.parametrize("summary", ["Uncited summary claim.", "Only bogus citations [42]."])
def test_uncited_summary_is_replaced(fake_llm, monkeypatch, summary):
    fake_llm.responses[Synthesis] = Synthesis(
        summary=summary, key_findings=["Cited finding [1]."]
    )
    monkeypatch.setattr(research, "serpapi_search", lambda q, k: _results(q.replace(" ", "-")))
    out = graph.invoke({"request": "Research AI trends"})
    report = out["final_output"]
    assert summary.split(" [")[0] not in report
    assert research.UNCITED_SUMMARY in report
    assert research.NO_SOURCES_SUMMARY not in report
    _citations_map_to_sources(report)
