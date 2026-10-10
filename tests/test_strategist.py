"""Offline tests for the Content Strategist: one test per I/O matrix row via graph.invoke.

The LLM is faked (tests/conftest.py) and research.serpapi_search is patched (the `serp`
fixture from tests/test_research.py), so no keys and no network are needed."""

from __future__ import annotations

import re

import pytest
from langchain_core.exceptions import OutputParserException

from content_agent import research
from content_agent.graph import graph
from content_agent.research import (
    MISSING_SERPAPI_KEY,
    NO_FINDINGS_LINE,
    NO_SOURCES_SUMMARY,
    Synthesis,
)
from content_agent.router import RouteDecision
from content_agent.strategist import NO_RESULTS_NOTE, Report
from tests import test_research
from tests.test_research import QUERIES, REQUEST, TOPIC, _fake, _openai_error, _results

serp = test_research.serp  # reuse the SerpAPI fixture

SECTIONS = ["# ", "## Executive Summary", "## Key Findings", "## Sources", "## Notes"]


def _headings(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("#")]


def _assert_report_citations_valid(out: str, n_sources: int) -> None:
    body = out.split("## Sources", 1)[0]
    for m in re.findall(r"\[(\d+)\]", body):
        assert 1 <= int(m) <= n_sources
    listed = re.findall(r"^(\d+)\. \[", out.split("## Sources", 1)[1], flags=re.MULTILINE)
    assert [int(x) for x in listed] == list(range(1, n_sources + 1))


def _three_sources(responses) -> None:
    responses[QUERIES[0]] = _results("a")
    responses[QUERIES[1]] = _results("b", 1)


def test_research_report(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(
        _fake(
            report=Report(
                title="AI Reshapes B2B Marketing [2]",
                executive_summary="AI adoption is rising [1][3], with bogus [9] claims removed.",
                what_this_means="Teams should pilot AI now [2][7].",
            )
        )
    )

    result = graph.invoke({"request": REQUEST})
    out = result["final_output"]

    assert result["intent"] == "research"
    assert result["errors"] == []
    assert fake.schemas_called() == [
        "RouteDecision", "QueryPlan", "Synthesis", "PostResearchDecision", "Report"
    ]
    assert _headings(out) == [
        "# AI Reshapes B2B Marketing",
        "## Executive Summary",
        "## Key Findings",
        "## Sources",
        "## Notes",
    ]
    assert "AI adoption is rising [1][3], with bogus claims removed." in out
    # Key Findings stay exactly as synthesis produced them.
    assert "- Most teams use AI for content [1].\n- Personalization drives ROI [2]." in out
    assert "1. [a title 1](https://example.com/a/1)\n2. [a title 2](https://example.com/a/2)\n3. [b title 1](https://example.com/b/1)" in out
    assert "**What this means:** Teams should pilot AI now [2]." in out
    assert "not built yet" not in out
    _assert_report_citations_valid(out, 3)


def test_no_notes_when_nothing_to_say(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    use_llm(_fake(report=Report(title="T", executive_summary="Fact [1].", what_this_means="  ")))

    out = graph.invoke({"request": REQUEST})["final_output"]

    assert _headings(out) == ["# T", "## Executive Summary", "## Key Findings", "## Sources"]


def test_fallbacks_for_blank_title_and_uncited_summary(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    use_llm(_fake(report=Report(title="  [3] ", executive_summary="Uncited [42] claim.", what_this_means="")))

    result = graph.invoke({"request": REQUEST})
    out = result["final_output"]

    assert out.startswith(f"# Research Report: {TOPIC}\n")
    assert f"## Executive Summary\n\n{result['findings']['summary']}\n" in out
    assert "[42]" not in out
    _assert_report_citations_valid(out, 3)


def test_linkedin_routed_to_report_has_no_writer_note(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    use_llm(_fake("linkedin"))

    result = graph.invoke({"request": REQUEST})
    out = result["final_output"]

    assert result["intent"] == "linkedin"
    assert result["target_format"] == "report"
    assert [h.split(" ", 1)[0] for h in _headings(out)] == ["#", "##", "##", "##", "##"]
    assert "not built yet" not in out
    _assert_report_citations_valid(out, 3)


def test_blog_intent_routed_to_report_has_no_writer_note(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    use_llm(_fake("blog"))  # router answers "report"

    out = graph.invoke({"request": REQUEST})["final_output"]

    assert "## Executive Summary" in out
    assert "not built yet" not in out


def test_search_problems_listed_in_notes(use_llm, serp):
    responses, _ = serp
    responses[QUERIES[0]] = _results("a")
    responses[QUERIES[1]] = RuntimeError("down")
    responses[QUERIES[2]] = _results("c", 2)
    use_llm(_fake())

    result = graph.invoke({"request": REQUEST})
    out = result["final_output"]

    assert len(result["errors"]) == 1
    assert _headings(out)[1:] == SECTIONS[1:]
    assert out.split("## Notes", 1)[1].rstrip().endswith(f"- {result['errors'][0]}")
    _assert_report_citations_valid(out, 4)


def _assert_no_sources_report(out: str) -> None:
    assert _headings(out) == [f"# Research Report: {TOPIC}", "## Executive Summary", "## Notes"]
    assert NO_SOURCES_SUMMARY in out
    assert "## Key Findings" not in out and "## Sources" not in out


def test_no_sources_missing_key(use_llm, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setattr(research, "serpapi_search", lambda *a, **k: pytest.fail("no search without a key"))
    fake = use_llm(_fake())

    result = graph.invoke({"request": REQUEST})
    out = result["final_output"]

    _assert_no_sources_report(out)
    assert f"- {MISSING_SERPAPI_KEY}" in out.split("## Notes", 1)[1]
    assert fake.schemas_called() == ["RouteDecision", "QueryPlan"]


def test_no_sources_no_results(use_llm, serp):
    fake = use_llm(_fake("blog"))  # every query returns []

    result = graph.invoke({"request": REQUEST})
    out = result["final_output"]

    assert result["errors"] == []
    _assert_no_sources_report(out)
    notes = out.split("## Notes", 1)[1]
    assert NO_RESULTS_NOTE in notes
    assert "not built yet" not in notes
    assert "Report" not in fake.schemas_called()
    assert "PostResearchDecision" not in fake.schemas_called()


def test_synthesis_failure_skips_strategist(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(_fake(errors={Synthesis: OutputParserException("bad")}))

    result = graph.invoke({"request": REQUEST})

    assert result["intent"] == "error"
    assert "Report" not in fake.schemas_called()
    assert "synthesize" in result["final_output"]
    assert "OutputParserException" in result["final_output"]
    assert result["errors"] == ["synthesize: OutputParserException"]


@pytest.mark.parametrize("error", [_openai_error(), OutputParserException("bad json")])
def test_strategist_llm_failure_ends_run(use_llm, serp, error):
    responses, _ = serp
    responses[QUERIES[0]] = RuntimeError("down")
    responses[QUERIES[1]] = _results("b", 1)
    use_llm(_fake(errors={Report: error}))

    result = graph.invoke({"request": REQUEST})

    kind = type(error).__name__
    assert result["intent"] == "error"
    assert kind in result["final_output"]
    assert "## Sources" not in result["final_output"]
    assert len(result["errors"]) == 2
    assert result["errors"][1] == f"content_strategist: {kind}"


def _assert_all_markers_listed(out: str, n_sources: int) -> None:
    for m in re.findall(r"\[(\d+)\]", out.split("## Sources", 1)[0]):
        assert 1 <= int(m) <= n_sources


def test_bracketed_topic_without_sources(use_llm, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    fake = _fake()
    fake.responses[RouteDecision] = RouteDecision(intent="research", topic="tools [2025] [3]")
    use_llm(fake)

    out = graph.invoke({"request": REQUEST})["final_output"]

    assert out.startswith("# Research Report: tools (2025) (3)\n")
    _assert_all_markers_listed(out, 0)


def test_bracketed_failed_query_in_notes(use_llm, serp):
    responses, _ = serp
    queries = ["tools [7]", QUERIES[1], QUERIES[2]]
    responses[queries[0]] = RuntimeError("down")
    responses[QUERIES[1]] = _results("b", 1)
    use_llm(_fake(queries=queries))

    result = graph.invoke({"request": REQUEST})
    out = result["final_output"]

    assert "Search failed for 'tools (7)': RuntimeError" in out.split("## Notes", 1)[1]
    _assert_all_markers_listed(out, 1)


def test_all_findings_dropped_uses_placeholder(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    use_llm(_fake(synthesis=Synthesis(summary="Fact [1].", key_findings=["Uncited.", "Bogus [9]."])))

    result = graph.invoke({"request": REQUEST})
    out = result["final_output"]

    assert result["findings"]["key_findings"] == []
    assert f"## Key Findings\n\n- {NO_FINDINGS_LINE}\n" in out
    _assert_report_citations_valid(out, 3)


def test_cleaned_synthesis_summary_reaches_report(use_llm, serp):
    responses, _ = serp
    responses[QUERIES[0]] = _results("a")  # 2 sources
    use_llm(
        _fake(
            synthesis=Synthesis(summary="Claim [99] and fact [2] [7].", key_findings=["Point [1]."]),
            report=Report(title="T", executive_summary="No citations here.", what_this_means=""),
        )
    )

    out = graph.invoke({"request": REQUEST})["final_output"]

    assert "## Executive Summary\n\nClaim and fact [2].\n" in out
    assert "[99]" not in out and "[7]" not in out
    _assert_report_citations_valid(out, 2)
