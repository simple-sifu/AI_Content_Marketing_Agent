"""Unit tests for content_agent.validators.validate_blog: each SEO rule, pass and fail.

Also holds the body/draft builders that tests/test_blog.py reuses."""

from __future__ import annotations

import json

import pytest

from content_agent.blog import BlogDraft
from content_agent.validators import (
    blog_body,
    body_words,
    keyword_density,
    keyword_mentions,
    meta_description,
    validate_blog,
)

KEYWORD = "remote work tools"
SOURCES = [
    {"title": "Source one", "url": "https://example.com/1", "snippet": "s1"},
    {"title": "Source two", "url": "https://example.com/2", "snippet": "s2"},
]
HEADINGS = ["## Why it matters", "### The details", "## What to do next"]
META = (
    "Learn how AI in B2B marketing is changing demand generation, content production and "
    "personalization for modern revenue teams today."
)


def make_body(
    keyword: str,
    total_words: int = 1000,
    mentions: int = 5,
    cite: str = "[1]",
    headings: list[str] | None = None,
) -> str:
    """A markdown body of exactly `total_words` words with `mentions` exact keyword phrases."""
    headings = HEADINGS if headings is None else headings
    heading_words = sum(len(h.lstrip("#").split()) for h in headings)
    filler = total_words - heading_words - mentions * len(keyword.split())
    assert filler > 0
    items = ["alpha"] * filler
    step = filler // (mentions + 1) if mentions else 0
    for i in range(mentions):
        items.insert((i + 1) * step + i, keyword)
    n = max(1, len(headings))
    size = -(-len(items) // n)
    parts: list[str] = []
    for i, start in enumerate(range(0, len(items), size)):
        if i < len(headings):
            parts.append(headings[i])
        parts.append(" ".join(items[start : start + size]) + f" {cite}.")
    return "\n\n".join(parts)


def draft(
    keyword: str, title: str = "A Practical Guide", meta: str = META, **body_kwargs
) -> BlogDraft:
    return BlogDraft(title=title, meta_description=meta, body=make_body(keyword, **body_kwargs))


def make_post(
    body: str | None = None,
    meta: str | None = META,
    title: str = "A Practical Guide",
    sources: list | None = None,
) -> str:
    sources = SOURCES if sources is None else sources
    front = "" if meta is None else f"---\nmeta_description: {json.dumps(meta)}\n---\n\n"
    listed = "\n".join(f"{i}. [{s['title']}]({s['url']})" for i, s in enumerate(sources, 1))
    body = make_body(KEYWORD) if body is None else body
    return f"{front}# {title}\n\n{body}\n\n## Sources\n\n{listed}\n"


def test_meta_fixture_length():
    assert 120 <= len(META) <= 160


def test_valid_post_passes():
    post = make_post()
    assert validate_blog(post, SOURCES, KEYWORD) == []
    assert body_words(post) == 1000
    assert keyword_density(post, KEYWORD) == pytest.approx(1.5)


def test_body_excludes_front_matter_title_and_sources():
    post = make_post(body="## A\n\nalpha beta [1].")
    assert blog_body(post).strip() == "## A\n\nalpha beta [1]."
    assert body_words(post) == 3  # citation markers are not words
    assert meta_description(post) == META


@pytest.mark.parametrize(
    ("mentions", "words", "keyword", "expected"),
    [
        (5, 1000, KEYWORD, 1.5),  # 5 x 3 / 1000
        (10, 1000, "tools", 1.0),
        (20, 1000, "tools", 2.0),
        (4, 1000, "AI in B2B marketing", 1.6),
    ],
)
def test_density_math(mentions, words, keyword, expected):
    post = make_post(body=make_body(keyword, total_words=words, mentions=mentions))
    assert keyword_density(post, keyword) == pytest.approx(expected)


def test_density_bounds_are_inclusive():
    for mentions in (10, 20):
        post = make_post(body=make_body("tools", mentions=mentions))
        assert validate_blog(post, SOURCES, "tools") == []


@pytest.mark.parametrize("mentions", [3, 7])  # 0.9% and 2.1%
def test_density_out_of_range_fails(mentions):
    post = make_post(body=make_body(KEYWORD, mentions=mentions))
    failures = validate_blog(post, SOURCES, KEYWORD)
    assert len(failures) == 1 and "density" in failures[0]


def test_keyword_match_is_case_insensitive_whole_phrase():
    text = "Remote Work Tools help. remote work toolsets do not. Remote  work tools again."
    assert keyword_mentions(text, KEYWORD) == 2
    assert keyword_mentions("intools tools-ish tools.", "tools") == 2


@pytest.mark.parametrize(
    ("meta", "fragment"),
    [
        ("Too short.", "meta_description is 10 characters"),
        ("x" * 161, "meta_description is 161 characters"),
        (None, "front matter"),
    ],
)
def test_meta_description_rules(meta, fragment):
    failures = validate_blog(make_post(meta=meta), SOURCES, KEYWORD)
    assert len(failures) == 1 and fragment in failures[0]


@pytest.mark.parametrize("length", [120, 160])
def test_meta_bounds_are_inclusive(length):
    assert validate_blog(make_post(meta="m" * length), SOURCES, KEYWORD) == []


def test_front_matter_without_meta_fails():
    post = make_post(meta=None)
    post = "---\ntitle: x\n---\n\n" + post
    failures = validate_blog(post, SOURCES, KEYWORD)
    assert failures == ["The front matter must contain meta_description."]


def test_exactly_one_h1():
    extra_h1 = make_post(body="# Extra\n\n" + make_body(KEYWORD))
    failures = validate_blog(extra_h1, SOURCES, KEYWORD)
    assert any("exactly one '# ' H1" in f and "found 2" in f for f in failures)

    no_h1 = make_post().replace("# A Practical Guide\n", "")
    assert any("found 0" in f for f in validate_blog(no_h1, SOURCES, KEYWORD))


def test_heading_structure():
    one_h2 = make_body(KEYWORD, headings=["## Only one", "### Sub"])
    failures = validate_blog(make_post(body=one_h2), SOURCES, KEYWORD)
    assert failures == ["The body needs at least two '## ' sections; found 1."]

    no_h3 = make_body(KEYWORD, headings=["## One", "## Two"])
    failures = validate_blog(make_post(body=no_h3), SOURCES, KEYWORD)
    assert failures == ["The body needs at least one '### ' subsection; found 0."]


def test_sources_heading_does_not_count_as_body_section():
    body = make_body(KEYWORD, headings=["## Only one", "### Sub"])
    assert "found 1" in validate_blog(make_post(body=body), SOURCES, KEYWORD)[0]


def test_minimum_body_words():
    post = make_post(body=make_body(KEYWORD, total_words=799, mentions=4))
    failures = validate_blog(post, SOURCES, KEYWORD)
    assert failures == ["The body has 799 words; it needs at least 800."]
    post = make_post(body=make_body(KEYWORD, total_words=800, mentions=4))
    assert validate_blog(post, SOURCES, KEYWORD) == []


@pytest.mark.parametrize("cite", ["[3]", "[0]", "[1][99]"])
def test_citations_must_map_to_sources(cite):
    post = make_post(body=make_body(KEYWORD, cite=cite))
    failures = validate_blog(post, SOURCES, KEYWORD)
    assert len(failures) == 1 and "do not map to a listed source" in failures[0]


def test_citation_in_title_or_meta_is_checked():
    post = make_post(title="Guide [7]")
    assert any("[7]" in f for f in validate_blog(post, SOURCES, KEYWORD))
    post = make_post(meta=META[:-6] + " [9]...")
    assert any("[9]" in f for f in validate_blog(post, SOURCES, KEYWORD))


def test_sources_section_rules():
    missing = make_post().split("## Sources", 1)[0]
    assert any("'## Sources' section" in f for f in validate_blog(missing, SOURCES, KEYWORD))

    reordered = make_post(sources=list(reversed(SOURCES)))
    assert any("in order" in f for f in validate_blog(reordered, SOURCES, KEYWORD))


def test_empty_keyword_fails():
    assert any("keyword" in f for f in validate_blog(make_post(), SOURCES, "  "))


@pytest.mark.parametrize(
    ("keyword", "text"),
    [
        ("Node.js frameworks", "Top node.js Frameworks today; Node.js frameworks win. NodeXjs frameworks is not it."),
        ("Notion vs. Slack", "Comparing Notion vs. Slack here; notion VS. slack again."),
        ("C++ tools", "Modern C++ tools help; c++ Tools are fast. C tools are not it."),
    ],
)
def test_punctuated_keywords_match_verbatim(keyword, text):
    assert keyword_mentions(text, keyword) == 2
    body = "## A\n\n" + text + "\n\n### B\n\n## C"
    assert keyword_density(make_post(body=body), keyword) > 0


def test_density_message_range_is_clamped():
    # 3-word keyword in a tiny body: unclamped range would read "1-0 mentions".
    post = make_post(body="## A\n\n### B\n\n## C\n\n" + " ".join(["alpha"] * 40))
    failures = validate_blog(post, SOURCES, KEYWORD)
    density = next(f for f in failures if "density" in f)
    assert "i.e. 1-1 mentions" in density
