"""Offline tests for the post-research router and SEO Blog Writer: one test per I/O matrix
row via graph.invoke, plus assembly details.

The LLM is faked (tests/conftest.py) and research.serpapi_search is patched (the `serp`
fixture from tests/test_research.py), so no keys and no network are needed."""

from __future__ import annotations

import re

import pytest
from langchain_core.exceptions import OutputParserException

from content_agent.blog import (
    MAX_REVISIONS,
    TARGET_WORDS,
    BlogDraft,
    _assemble,
    _keyword_usage,
    _mention_range,
    blog_writer,
)
from content_agent.graph import graph
from content_agent.router import PostResearchDecision
from content_agent.validators import keyword_density, validate_blog
from tests import test_research
from tests.conftest import FakeLLM
from tests.test_research import QUERIES, REQUEST, TOPIC, _fake, _openai_error, _results
from tests.test_validators import META, draft, make_body

serp = test_research.serp  # reuse the SerpAPI fixture

BLOG_REQUEST = "Write a blog post about AI in B2B marketing"


def _three_sources(responses) -> None:
    responses[QUERIES[0]] = _results("a")
    responses[QUERIES[1]] = _results("b", 1)


def _blog_fake(drafts, intent: str = "blog", target_format: str = "blog", **kwargs):
    fake = _fake(intent, target_format=target_format, **kwargs)
    fake.responses[BlogDraft] = drafts
    return fake


def _good(**kwargs) -> BlogDraft:
    return draft(TOPIC, mentions=4, **kwargs)  # 4 x 4 words / 1000 = 1.6%


def test_blog_request_writes_valid_post(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(_blog_fake(_good(title="AI in B2B Marketing [Updated] Guide [2]")))

    result = graph.invoke({"request": BLOG_REQUEST})
    out = result["final_output"]

    assert result["intent"] == "blog"
    assert result["target_format"] == "blog"
    assert result["errors"] == []
    assert validate_blog(out, result["sources"], result["topic"]) == []
    assert fake.schemas_called() == [
        "RouteDecision", "QueryPlan", "Synthesis", "PostResearchDecision", "BlogDraft"
    ]
    assert out.startswith(f'---\nmeta_description: "{META}"\n---\n\n# AI in B2B Marketing (Updated) Guide\n')
    assert out.rstrip().endswith(
        "## Sources\n\n1. [a title 1](https://example.com/a/1)\n"
        "2. [a title 2](https://example.com/a/2)\n3. [b title 1](https://example.com/b/1)"
    )
    # The writer gets the cited findings and numbered sources.
    prompt = fake.calls[-1][1]
    assert "Most teams use AI for content [1]." in prompt
    assert "[3] b title 1" in prompt
    assert f'"{TOPIC}"' in prompt


@pytest.mark.parametrize("intent", ["research", "linkedin"])
def test_report_requests_get_strategist_report(use_llm, serp, intent):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(_fake(intent))  # router answers "report"

    result = graph.invoke({"request": REQUEST})
    out = result["final_output"]

    assert result["target_format"] == "report"
    assert "BlogDraft" not in fake.schemas_called()
    assert fake.schemas_called()[-2:] == ["PostResearchDecision", "Report"]
    assert "## Executive Summary" in out
    assert "not built yet" not in out
    # The router sees the request and the classified intent.
    router_prompt = fake.calls[3][1]
    assert REQUEST in router_prompt and f"Classified intent: {intent}" in router_prompt


def test_blog_with_no_sources_skips_router(use_llm, serp):
    fake = use_llm(_blog_fake(_good()))  # every query returns []

    result = graph.invoke({"request": BLOG_REQUEST})
    out = result["final_output"]

    assert result["sources"] == []
    assert result["target_format"] == ""  # cleared at the start of every run
    assert "PostResearchDecision" not in fake.schemas_called()
    assert "BlogDraft" not in fake.schemas_called()
    assert out.startswith(f"# Research Report: {TOPIC}\n")


def test_density_fixed_on_revision(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    too_dense = draft(TOPIC, title="First", mentions=8)  # 3.2%
    fixed = draft(TOPIC, title="Second", mentions=4)  # 1.6%
    fake = use_llm(_blog_fake([too_dense, fixed]))

    result = graph.invoke({"request": BLOG_REQUEST})
    out = result["final_output"]

    assert fake.schemas_called().count("BlogDraft") == 2
    revision_prompt = fake.calls[-1][1]
    assert "density is 3.20%" in revision_prompt
    assert "title: First" in revision_prompt
    assert "# Second\n" in out
    assert keyword_density(out, TOPIC) == pytest.approx(1.6)
    assert result["errors"] == []


def test_still_invalid_after_revisions(use_llm, serp):
    responses, _ = serp
    responses[QUERIES[0]] = RuntimeError("down")  # an earlier error that must survive
    responses[QUERIES[1]] = _results("b", 3)
    bad = [
        draft(TOPIC, title=f"Draft {i}", mentions=8, headings=["## One", "## Two"])
        for i in range(1, MAX_REVISIONS + 2)
    ]
    fake = use_llm(_blog_fake(bad))

    result = graph.invoke({"request": BLOG_REQUEST})
    out = result["final_output"]

    assert fake.schemas_called().count("BlogDraft") == MAX_REVISIONS + 1
    assert f"# Draft {MAX_REVISIONS + 1}\n" in out
    failures = validate_blog(out, result["sources"], TOPIC)
    assert len(failures) == 2
    assert result["errors"][0].startswith("Search failed for")
    assert result["errors"][1:] == [f"blog_writer: SEO check failed: {f}" for f in failures]
    assert result["intent"] == "blog"


def test_bad_citations_and_stray_h1_are_fixed(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    body = make_body(TOPIC, mentions=4, cite="[2][99]", headings=["# Stray", "### Sub", "## Two"])
    stray = BlogDraft(title="# Guide [1]", meta_description=META[:-7] + " [9] now.", body=body)
    use_llm(_blog_fake(stray))

    result = graph.invoke({"request": BLOG_REQUEST})
    out = result["final_output"]

    assert "[99]" not in out and "[9]" not in out
    assert "## Stray" in out
    assert [line for line in out.splitlines() if line.startswith("# ")] == ["# Guide"]
    assert validate_blog(out, result["sources"], TOPIC) == []
    assert result["errors"] == []


def test_llm_sources_section_and_repeated_title_are_dropped(use_llm):
    sources = [{"title": "S", "url": "https://s.example", "snippet": ""}]
    body = "# Guide\n\n" + make_body(TOPIC, mentions=4) + "\n\n## Sources\n\n1. [Made up](https://x)"
    use_llm(FakeLLM({BlogDraft: BlogDraft(title="Guide", meta_description=META, body=body)}))
    state = {"topic": TOPIC, "sources": sources, "findings": {}, "errors": []}

    out = blog_writer(state)["final_output"]

    assert "Made up" not in out
    assert out.count("## Sources") == 1
    assert re.findall(r"^#{1,2} Guide$", out, flags=re.MULTILINE) == ["# Guide"]
    assert validate_blog(out, sources, TOPIC) == []


@pytest.mark.parametrize("error", [_openai_error(), OutputParserException("bad json")])
@pytest.mark.parametrize(
    ("schema", "node"),
    [(PostResearchDecision, "post_research_router"), (BlogDraft, "blog_writer")],
)
def test_router_or_writer_llm_failure_ends_run(use_llm, serp, error, schema, node):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(_blog_fake(_good(), errors={schema: error}))

    result = graph.invoke({"request": BLOG_REQUEST})

    kind = type(error).__name__
    assert result["intent"] == "error"
    assert kind in result["final_output"]
    assert result["errors"] == [f"{node}: {kind}"]
    assert "Report" not in fake.schemas_called()
    if node == "post_research_router":
        assert result["target_format"] == ""
        assert "BlogDraft" not in fake.schemas_called()


def test_writer_failure_during_revision_ends_run(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(_blog_fake([draft(TOPIC, mentions=8), OutputParserException("bad revision")]))

    result = graph.invoke({"request": BLOG_REQUEST})

    assert fake.schemas_called().count("BlogDraft") == 2
    assert result["intent"] == "error"
    assert result["errors"] == ["blog_writer: OutputParserException"]


@pytest.mark.parametrize(
    ("mentions", "action"),
    [
        (8, "remove 4 of them"),
        (1, "add 3 more (one in each of these sections:"),
        (4, "keep that number"),
    ],
)
def test_keyword_usage_hint(mentions, action):
    # 1000 body words, 4-word topic: target round(1.5 * 1000 / 100 / 4) = 4 mentions.
    post = _assemble(draft(TOPIC, mentions=mentions), TOPIC, [])
    hint = _keyword_usage(post, TOPIC)
    assert f'uses the exact phrase "{TOPIC}" {mentions} times' in hint
    assert "the target is 4" in hint and action in hint


def test_mid_body_references_section_survives(use_llm):
    sources = [{"title": "S", "url": "https://s.example", "snippet": ""}]
    body = make_body(TOPIC, mentions=4).replace(
        "### The details", "## References\n\nSee the studies below [1].\n\n### The details"
    )
    trailing = body + "\n\n## References\n\n1. [Made up](https://x)"
    use_llm(FakeLLM({BlogDraft: BlogDraft(title="Guide", meta_description=META, body=trailing)}))
    state = {"topic": TOPIC, "sources": sources, "findings": {}, "errors": []}

    out = blog_writer(state)["final_output"]

    assert "## References\n\nSee the studies below [1]." in out
    assert "### The details" in out
    assert "Made up" not in out


@pytest.mark.parametrize(
    ("keyword", "expected"),
    [("tools", (16, 24)), ("remote work tools", (6, 8)), (TOPIC, (4, 6))],
)
def test_mention_budget_fits_whole_requested_length(keyword, expected):
    lo, hi = _mention_range(keyword)
    assert (lo, hi) == expected
    k = len(keyword.split())
    for words in TARGET_WORDS:
        for m in (lo, hi):
            assert 1 <= m * k / words * 100 <= 2
