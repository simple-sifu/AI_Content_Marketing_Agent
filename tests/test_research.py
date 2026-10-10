"""Offline tests for the Deep Research agent: one test per I/O matrix row via graph.invoke.

The LLM is faked (tests/conftest.py) and research.serpapi_search is patched, so no
OpenAI or SerpAPI key and no network are needed."""

from __future__ import annotations

import re

import httpx
import openai
import pytest
from langchain_core.exceptions import OutputParserException
from langgraph.checkpoint.memory import InMemorySaver

from content_agent import research
from content_agent.graph import build_graph, graph
from content_agent.images import ImagePrompt
from content_agent.research import (
    MISSING_SERPAPI_KEY,
    NO_SOURCES_SUMMARY,
    UNCITED_SUMMARY,
    QueryPlan,
    SerpAPIError,
    Synthesis,
)
from content_agent.router import PostResearchDecision, RouteDecision
from content_agent.strategist import Report
from tests.conftest import FakeLLM, png_b64

SERP_KEY = "serp-SECRET-key-987"
TOPIC = "AI in B2B marketing"
REQUEST = "Give me an overview of AI in B2B marketing"
QUERIES = ["AI B2B marketing overview", "AI B2B marketing statistics 2026", "AI B2B marketing case studies"]


def _results(prefix: str, n: int = 2) -> list[dict]:
    return [
        {"title": f"{prefix} title {i}", "link": f"https://example.com/{prefix}/{i}", "snippet": f"{prefix} snippet {i}"}
        for i in range(1, n + 1)
    ]


def _fake(
    intent: str = "research",
    queries: list[str] | None = None,
    synthesis: Synthesis | None = None,
    errors: dict | None = None,
    report: Report | None = None,
    target_format: str = "report",
) -> FakeLLM:
    return FakeLLM(
        {
            RouteDecision: RouteDecision(intent=intent, topic=TOPIC),
            QueryPlan: QueryPlan(queries=QUERIES if queries is None else queries),
            Synthesis: synthesis
            or Synthesis(
                summary="AI adoption in B2B marketing is rising [1][3].",
                key_findings=["Most teams use AI for content [1].", "Personalization drives ROI [2][4]."],
            ),
            PostResearchDecision: PostResearchDecision(target_format=target_format),
            Report: report
            or Report(
                title="AI in B2B Marketing",
                executive_summary="AI is now core to B2B marketing [1].",
                what_this_means="Teams should invest in AI skills.",
            ),
        },
        errors=errors,
    )


@pytest.fixture
def serp(monkeypatch):
    """Patch the single SerpAPI call site. `responses` maps query -> results list or exception."""
    monkeypatch.setenv("SERPAPI_API_KEY", SERP_KEY)
    calls: list[tuple[str, str]] = []
    responses: dict = {}

    def fake_search(query: str, api_key: str):
        calls.append((query, api_key))
        outcome = responses.get(query, [])
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(research, "serpapi_search", fake_search)
    return responses, calls


def _assert_citations_valid(result: dict) -> None:
    n = len(result["sources"])
    texts = [result["findings"]["summary"], *result["findings"]["key_findings"]]
    for text in texts:
        for m in re.findall(r"\[(\d+)\]", text):
            assert 1 <= int(m) <= n


@pytest.mark.parametrize("intent", ["research", "blog", "linkedin"])
def test_happy_path(use_llm, serp, intent):
    responses, calls = serp
    # Overlapping URL between query 1 and 2 must be deduped.
    responses[QUERIES[0]] = _results("a")
    responses[QUERIES[1]] = [_results("a")[1], *_results("b", 1)]
    responses[QUERIES[2]] = _results("c", 1)
    fake = use_llm(_fake(intent))

    result = graph.invoke({"request": REQUEST})

    assert result["intent"] == intent
    assert result["queries"] == QUERIES
    assert [q for q, _ in calls] == QUERIES
    assert all(k == SERP_KEY for _, k in calls)
    assert [s["url"] for s in result["sources"]] == [
        "https://example.com/a/1",
        "https://example.com/a/2",
        "https://example.com/b/1",
        "https://example.com/c/1",
    ]
    assert result["findings"]["summary"] == "AI adoption in B2B marketing is rising [1][3]."
    assert result["findings"]["key_findings"] == [
        "Most teams use AI for content [1].",
        "Personalization drives ROI [2][4].",
    ]
    assert result["errors"] == []
    out = result["final_output"]
    assert "- Most teams use AI for content [1]." in out
    assert "## Sources" in out
    assert "1. [a title 1](https://example.com/a/1)" in out
    assert "4. [c title 1](https://example.com/c/1)" in out
    assert fake.schemas_called() == [
        "RouteDecision", "QueryPlan", "Synthesis", "PostResearchDecision", "Report"
    ]
    assert result["target_format"] == "report"
    # The synthesis prompt numbers sources from 1 in list order.
    assert "[4] c title 1" in fake.calls[2][1]
    _assert_citations_valid(result)


@pytest.mark.parametrize(
    "llm_queries",
    [
        [],
        ["only one"],
        ["dup", "DUP", "  dup  "],
        ["q1", "q2", "q3", "q4"],
    ],
)
def test_always_three_distinct_queries(use_llm, serp, llm_queries):
    _, calls = serp
    use_llm(_fake(queries=llm_queries))

    result = graph.invoke({"request": REQUEST})

    assert len(result["queries"]) == 3
    assert len({q.lower() for q in result["queries"]}) == 3
    assert [q for q, _ in calls] == result["queries"]


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("boom"), SerpAPIError("Your account has run out of searches.")],
)
def test_partial_failure_is_isolated(use_llm, serp, failure):
    responses, calls = serp
    responses[QUERIES[0]] = _results("a")
    responses[QUERIES[1]] = failure
    responses[QUERIES[2]] = _results("c", 2)
    use_llm(_fake())

    result = graph.invoke({"request": REQUEST})

    assert len(calls) == 3
    assert [s["url"] for s in result["sources"]] == [
        "https://example.com/a/1",
        "https://example.com/a/2",
        "https://example.com/c/1",
        "https://example.com/c/2",
    ]
    assert len(result["errors"]) == 1
    if isinstance(failure, SerpAPIError):
        assert result["errors"][0] == (
            f"Search failed for {QUERIES[1]!r}: SerpAPI error: Your account has run out of searches."
        )
    else:
        assert result["errors"][0] == f"Search failed for {QUERIES[1]!r}: RuntimeError"
        assert "boom" not in result["errors"][0]
        assert "boom" not in result["final_output"]
    assert result["findings"]["key_findings"]
    notes = result["final_output"].split("## Notes", 1)[1]
    assert f"- {result['errors'][0]}" in notes
    assert result["intent"] == "research"


def test_all_searches_fail_or_empty(use_llm, serp):
    responses, _ = serp
    responses[QUERIES[0]] = RuntimeError("down")
    responses[QUERIES[1]] = []
    responses[QUERIES[2]] = SerpAPIError("Invalid request")
    fake = use_llm(_fake())

    result = graph.invoke({"request": REQUEST})

    assert result["sources"] == []
    assert result["findings"] == {"summary": NO_SOURCES_SUMMARY, "key_findings": []}
    assert "Synthesis" not in fake.schemas_called()
    assert "Report" not in fake.schemas_called()
    assert len(result["errors"]) == 2
    out = result["final_output"]
    assert NO_SOURCES_SUMMARY in out
    notes = out.split("## Notes", 1)[1]
    assert all(f"- {e}" in notes for e in result["errors"])
    assert "## Sources" not in out


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_serpapi_key(use_llm, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("SERPAPI_API_KEY", value)

    def boom(*a, **k):
        raise AssertionError("no search may run without a key")

    monkeypatch.setattr(research, "serpapi_search", boom)
    fake = use_llm(_fake())

    result = graph.invoke({"request": REQUEST})

    assert result["errors"] == [MISSING_SERPAPI_KEY]
    assert "SERPAPI_API_KEY" in result["errors"][0]
    assert result["sources"] == []
    assert result["findings"]["summary"] == NO_SOURCES_SUMMARY
    assert "Synthesis" not in fake.schemas_called()
    assert NO_SOURCES_SUMMARY in result["final_output"]
    assert MISSING_SERPAPI_KEY in result["final_output"]


def test_key_never_leaks(use_llm, serp):
    responses, _ = serp
    url = f"https://serpapi.com/search?q=x&api_key={SERP_KEY}"
    responses[QUERIES[0]] = httpx.HTTPStatusError(
        f"Client error for url {url}",
        request=httpx.Request("GET", url),
        response=httpx.Response(401),
    )
    responses[QUERIES[1]] = SerpAPIError(f"Invalid API key: {SERP_KEY}")
    responses[QUERIES[2]] = _results("c", 1)
    use_llm(_fake(synthesis=Synthesis(summary="Fact [1].", key_findings=["Point [1]."])))

    result = graph.invoke({"request": REQUEST})

    assert len(result["errors"]) == 2
    assert "HTTPStatusError" in result["errors"][0]
    assert "Invalid API key: ***" in result["errors"][1]
    assert SERP_KEY not in result["final_output"]
    assert all(SERP_KEY not in e for e in result["errors"])


def test_bad_citations_are_cleaned(use_llm, serp):
    responses, _ = serp
    responses[QUERIES[0]] = _results("a")  # 2 sources in total
    use_llm(
        _fake(
            synthesis=Synthesis(
                summary="Big claim [99]. Another [7], uncited.",
                key_findings=[
                    "Valid point [1][99].",
                    "No citation at all.",
                    "Only bogus [7].",
                    "Zero is bogus [0] but two is fine [2].",
                ],
            )
        )
    )

    result = graph.invoke({"request": REQUEST})

    assert len(result["sources"]) == 2
    assert result["findings"]["summary"] == UNCITED_SUMMARY
    assert result["findings"]["key_findings"] == [
        "Valid point [1].",
        "Zero is bogus but two is fine [2].",
    ]
    assert "[99]" not in result["final_output"]
    assert "[7]" not in result["final_output"]
    assert research._clean_citations("Big claim [99].", 2) == "Big claim."
    assert research._clean_citations("A [9], then B [1]; C [0]!", 2) == "A, then B [1]; C!"
    _assert_citations_valid(result)


def test_bracketed_title_is_not_a_citation(use_llm, serp):
    responses, _ = serp
    responses[QUERIES[0]] = [
        {"title": "Best AI tools [2025] [3]", "link": "https://example.com/x", "snippet": "s"}
    ]
    fake = use_llm(_fake(synthesis=Synthesis(summary="Fact [1].", key_findings=["Point [1]."])))

    result = graph.invoke({"request": REQUEST})

    assert result["sources"][0]["title"] == "Best AI tools (2025) (3)"
    assert "1. [Best AI tools (2025) (3)](https://example.com/x)" in result["final_output"]
    markers = {int(m) for m in re.findall(r"\[(\d+)\]", result["final_output"])}
    assert markers <= {1}
    assert "[2025]" not in fake.calls[2][1]


def _openai_error():
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.RateLimitError("slow down", response=httpx.Response(429, request=request), body=None)


@pytest.mark.parametrize("error", [_openai_error(), OutputParserException("bad json")])
@pytest.mark.parametrize(("schema", "node"), [(QueryPlan, "generate_queries"), (Synthesis, "synthesize")])
def test_llm_failure_ends_run(use_llm, serp, error, schema, node):
    responses, calls = serp
    responses[QUERIES[0]] = _results("a")
    use_llm(_fake(errors={schema: error}))

    result = graph.invoke({"request": REQUEST})

    kind = type(error).__name__
    assert result["intent"] == "error"
    assert kind in result["final_output"]
    assert result["errors"] == [f"{node}: {kind}"]
    if node == "generate_queries":
        assert calls == []
        assert result["queries"] == [] and result["sources"] == []


def test_research_failure_keeps_earlier_search_errors(use_llm, serp):
    responses, _ = serp
    responses[QUERIES[0]] = RuntimeError("down")
    responses[QUERIES[1]] = _results("b", 1)
    use_llm(_fake(errors={Synthesis: OutputParserException("bad")}))

    result = graph.invoke({"request": REQUEST})

    assert len(result["errors"]) == 2
    assert QUERIES[0] in result["errors"][0]
    assert result["errors"][1] == "synthesize: OutputParserException"


def test_image_intent_skips_research(use_llm, use_images, serp):
    _, calls = serp
    fake = use_llm(_fake(intent="image"))
    fake.responses[ImagePrompt] = ImagePrompt(prompt="A chart-filled office at dawn.")
    use_images([png_b64()])

    result = graph.invoke({"request": "Make an image of AI in B2B marketing"})

    assert calls == []
    assert fake.schemas_called() == ["RouteDecision", "ImagePrompt"]
    assert "queries" not in result and "sources" not in result
    assert result["image_model"] == "gpt-image-1"


def test_thread_reuse_overwrites_research_fields(use_llm, serp):
    responses, _ = serp
    threaded = build_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "r1"}}

    responses[QUERIES[0]] = RuntimeError("down")
    responses[QUERIES[1]] = _results("b", 1)
    use_llm(_fake())
    first = threaded.invoke({"request": REQUEST}, config)
    assert len(first["errors"]) == 1 and first["sources"]

    # Second run: query generation fails -> research fields reset, no stale errors.
    use_llm(_fake(errors={QueryPlan: OutputParserException("bad")}))
    second = threaded.invoke({"request": REQUEST}, config)

    assert second["errors"] == ["generate_queries: OutputParserException"]
    assert second["queries"] == []
    assert second["sources"] == []
    assert second["findings"] == {"summary": "", "key_findings": []}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"organic_results": _results("a", 1)}, _results("a", 1)),
        ({"error": "Google hasn't returned any results for this query."}, []),
        ({}, []),
        ({"error": f"Invalid API key: {SERP_KEY}"}, SerpAPIError),
    ],
)
def test_serpapi_search_maps_responses(monkeypatch, payload, expected):
    import serpapi

    seen = {}

    class FakeGoogleSearch:
        def __init__(self, params):
            seen.update(params)
            self.timeout = 60000

        def get_dict(self):
            seen["timeout"] = self.timeout
            return payload

    monkeypatch.setattr(serpapi, "GoogleSearch", FakeGoogleSearch)

    if expected is SerpAPIError:
        with pytest.raises(SerpAPIError):
            research.serpapi_search("q", SERP_KEY)
    else:
        assert research.serpapi_search("q", SERP_KEY) == expected
    assert seen["q"] == "q" and seen["api_key"] == SERP_KEY
    assert seen["timeout"] == research.SEARCH_TIMEOUT_SECONDS
