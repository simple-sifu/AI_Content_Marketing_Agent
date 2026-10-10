"""Offline tests for the LinkedIn Writer and its routing: one test per I/O matrix row via
graph.invoke, plus assembly details.

The LLM is faked (tests/conftest.py) and research.serpapi_search is patched (the `serp`
fixture from tests/test_research.py), so no keys and no network are needed."""

from __future__ import annotations

import pytest
from langchain_core.exceptions import OutputParserException

from content_agent.blog import BlogDraft
from content_agent.graph import graph
from content_agent.linkedin import MAX_REVISIONS, LinkedInDraft, _assemble, linkedin_writer
from content_agent.router import PostResearchDecision
from content_agent.validators import linkedin_post_text, linkedin_source_urls, validate_blog, validate_linkedin
from tests import test_research
from tests.conftest import FakeLLM
from tests.test_research import QUERIES, REQUEST, TOPIC, _fake, _openai_error, _results
from tests.test_validators import CTA, HOOK, TAGS, draft, linkedin_draft

serp = test_research.serp  # reuse the SerpAPI fixture

LINKEDIN_REQUEST = "Write a LinkedIn post about AI in B2B marketing"
URLS = ["https://example.com/a/1", "https://example.com/a/2", "https://example.com/b/1"]


def _three_sources(responses) -> None:
    responses[QUERIES[0]] = _results("a")
    responses[QUERIES[1]] = _results("b", 1)


def _linkedin_fake(drafts, intent: str = "linkedin", target_format: str = "linkedin", **kwargs):
    fake = _fake(intent, target_format=target_format, **kwargs)
    fake.responses[LinkedInDraft] = drafts
    return fake


def test_linkedin_request_writes_valid_post(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(_linkedin_fake(linkedin_draft(source_numbers=[3, 1])))

    result = graph.invoke({"request": LINKEDIN_REQUEST})
    out = result["final_output"]

    assert result["intent"] == "linkedin"
    assert result["target_format"] == "linkedin"
    assert result["errors"] == []
    assert validate_linkedin(out, result["sources"]) == []
    assert fake.schemas_called() == [
        "RouteDecision", "QueryPlan", "Synthesis", "PostResearchDecision", "LinkedInDraft"
    ]
    assert out.startswith(f"{HOOK}\n\n")
    assert f"\n\n{CTA}\n\n{' '.join(TAGS)}\n\nSources:\n" in out
    assert linkedin_source_urls(out) == [URLS[0], URLS[2]]  # source order, not draft order
    assert len(linkedin_post_text(out)) == 1450
    # The writer gets the cited findings and numbered sources.
    prompt = fake.calls[-1][1]
    assert "Most teams use AI for content [1]." in prompt
    assert "[3] b title 1" in prompt
    assert TOPIC in prompt


@pytest.mark.parametrize(
    ("intent", "target_format", "schema"),
    [("blog", "blog", "BlogDraft"), ("research", "report", "Report")],
)
def test_blog_and_research_requests_unchanged(use_llm, serp, intent, target_format, schema):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(_fake(intent, target_format=target_format))
    fake.responses[BlogDraft] = draft(TOPIC, mentions=4)

    result = graph.invoke({"request": REQUEST})
    out = result["final_output"]

    assert result["target_format"] == target_format
    assert fake.schemas_called()[-1] == schema
    assert "LinkedInDraft" not in fake.schemas_called()
    assert "not built yet" not in out
    if intent == "blog":
        assert validate_blog(out, result["sources"], TOPIC) == []
    else:
        assert "## Executive Summary" in out


def test_router_prompt_offers_linkedin(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(_linkedin_fake(linkedin_draft()))

    graph.invoke({"request": LINKEDIN_REQUEST})

    router_prompt = fake.calls[3][1]
    assert fake.calls[3][0] == "PostResearchDecision"
    assert "- linkedin: the user asked for a LinkedIn post." in router_prompt
    assert "Classified intent: linkedin" in router_prompt


def test_linkedin_with_no_sources_skips_router(use_llm, serp):
    fake = use_llm(_linkedin_fake(linkedin_draft()))  # every query returns []

    result = graph.invoke({"request": LINKEDIN_REQUEST})

    assert result["sources"] == []
    assert "target_format" not in result
    assert "PostResearchDecision" not in fake.schemas_called()
    assert "LinkedInDraft" not in fake.schemas_called()
    assert result["final_output"].startswith(f"# Research Report: {TOPIC}\n")


def test_too_short_fixed_on_revision(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    short, fixed = linkedin_draft(total=900), linkedin_draft(total=1450, hook="Second hook.")
    fake = use_llm(_linkedin_fake([short, fixed]))

    result = graph.invoke({"request": LINKEDIN_REQUEST})
    out = result["final_output"]

    assert fake.schemas_called().count("LinkedInDraft") == 2
    revision_prompt = fake.calls[-1][1]
    assert "The post is 900 characters" in revision_prompt
    assert "add about 550 characters" in revision_prompt
    assert f"hook: {HOOK}" in revision_prompt
    assert out.startswith("Second hook.\n\n")
    assert validate_linkedin(out, result["sources"]) == []
    assert result["errors"] == []


def test_still_invalid_after_revisions(use_llm, serp):
    responses, _ = serp
    responses[QUERIES[0]] = RuntimeError("down")  # an earlier error that must survive
    responses[QUERIES[1]] = _results("b", 3)
    bad = [linkedin_draft(total=900, tags=TAGS[:5], hook=f"Draft {i}.") for i in range(1, MAX_REVISIONS + 2)]
    fake = use_llm(_linkedin_fake(bad))

    result = graph.invoke({"request": LINKEDIN_REQUEST})
    out = result["final_output"]

    assert fake.schemas_called().count("LinkedInDraft") == MAX_REVISIONS + 1
    assert out.startswith(f"Draft {MAX_REVISIONS + 1}.\n\n")
    failures = validate_linkedin(out, result["sources"])
    assert len(failures) == 2
    assert result["errors"][0].startswith("Search failed for")
    assert result["errors"][1:] == [f"linkedin_writer: LinkedIn check failed: {f}" for f in failures]
    assert result["intent"] == "linkedin"


def test_messy_draft_is_cleaned(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    tags = ["AI", "#ai", "# B2B", "#Content-Marketing", *[f"Tag{i}" for i in range(11)]]  # 15 tags, 14 unique after normalizing; capped at 12
    clean = linkedin_draft()
    messy = linkedin_draft(
        hook="## " + HOOK.replace("AI.", "AI [2]."),
        story=clean.story.replace("Teams that", "**Teams** that #AI", 1).replace("wait.", "wait [99].", 1),
        cta=CTA,
        hashtags=tags,
        source_numbers=[99],
    )
    use_llm(_linkedin_fake(messy))

    result = graph.invoke({"request": LINKEDIN_REQUEST})
    out = result["final_output"]
    text = linkedin_post_text(out)

    assert "[2]" not in out and "[99]" not in out and "**" not in out and "## " not in out
    assert out.startswith(HOOK + "\n\n")
    assert "Teams that AI test small" in text  # inline hashtag kept as a plain word
    tag_line = text.splitlines()[-1].split()
    assert tag_line[:3] == ["#AI", "#B2B", "#ContentMarketing"]
    assert len(tag_line) == 12
    assert linkedin_source_urls(out) == URLS  # source_numbers all invalid: first 3


def test_assemble_without_sources_named_uses_first_three():
    sources = [{"title": f"t{i}", "url": f"https://s/{i}", "snippet": ""} for i in range(1, 6)]
    post = _assemble(linkedin_draft(source_numbers=[]), sources)
    assert linkedin_source_urls(post) == ["https://s/1", "https://s/2", "https://s/3"]
    post = _assemble(linkedin_draft(source_numbers=[5, 5, 4, 1, 2, 3, 0]), sources)
    assert linkedin_source_urls(post) == [f"https://s/{i}" for i in range(1, 6)]


def test_valid_post_leaves_errors_untouched(use_llm):
    sources = [{"title": "S", "url": "https://s.example", "snippet": ""}]
    use_llm(FakeLLM({LinkedInDraft: linkedin_draft()}))
    state = {"topic": TOPIC, "sources": sources, "findings": {}, "errors": ["earlier"]}

    result = linkedin_writer(state)

    assert "errors" not in result  # valid post: errors untouched
    assert validate_linkedin(result["final_output"], sources) == []


@pytest.mark.parametrize("error", [_openai_error(), OutputParserException("bad json")])
@pytest.mark.parametrize(
    ("schema", "node"),
    [(PostResearchDecision, "post_research_router"), (LinkedInDraft, "linkedin_writer")],
)
def test_router_or_writer_llm_failure_ends_run(use_llm, serp, error, schema, node):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(_linkedin_fake(linkedin_draft(), errors={schema: error}))

    result = graph.invoke({"request": LINKEDIN_REQUEST})

    kind = type(error).__name__
    assert result["intent"] == "error"
    assert kind in result["final_output"]
    assert result["errors"] == [f"{node}: {kind}"]
    assert "Report" not in fake.schemas_called()
    if node == "post_research_router":
        assert "LinkedInDraft" not in fake.schemas_called()


def test_writer_failure_during_revision_ends_run(use_llm, serp):
    responses, _ = serp
    _three_sources(responses)
    fake = use_llm(_linkedin_fake([linkedin_draft(total=900), OutputParserException("bad revision")]))

    result = graph.invoke({"request": LINKEDIN_REQUEST})

    assert fake.schemas_called().count("LinkedInDraft") == 2
    assert result["intent"] == "error"
    assert result["errors"] == ["linkedin_writer: OutputParserException"]


@pytest.mark.parametrize("field", ["hook", "cta"])
def test_empty_hook_or_cta_triggers_revision(use_llm, field):
    sources = [{"title": "S", "url": "https://s.example", "snippet": ""}]
    empty = linkedin_draft(**{field: "## [1]"})
    fake = use_llm(FakeLLM({LinkedInDraft: [empty, linkedin_draft()]}))
    state = {"topic": TOPIC, "sources": sources, "findings": {}, "errors": []}

    result = linkedin_writer(state)

    assert fake.schemas_called() == ["LinkedInDraft", "LinkedInDraft"]
    assert f"- The {field} is empty." in fake.calls[-1][1]
    assert "errors" not in result
    assert validate_linkedin(result["final_output"], sources) == []
