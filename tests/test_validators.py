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
    cite: str = "[1][2]",
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
        chunk = items[start : start + size]
        half = len(chunk) // 2  # cite mid-paragraph and at the end, as a real post would
        parts.append(" ".join(chunk[:half]) + f" {cite}. " + " ".join(chunk[half:]) + f" {cite}.")
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


@pytest.mark.parametrize("bad", ["[3]", "[0]", "[99]"])
def test_citations_must_map_to_sources(bad):
    post = make_post(body=make_body(KEYWORD, cite=f"[1][2]{bad}"))
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


# --- LinkedIn ----------------------------------------------------------------------------

from content_agent.linkedin import LinkedInDraft  # noqa: E402
from content_agent.validators import (  # noqa: E402
    hashtags,
    linkedin_post_text,
    linkedin_source_urls,
    validate_linkedin,
)

HOOK = "Most B2B teams already use AI. Few use it well."
CTA = "How is your team using AI this quarter? Tell me in the comments."
TAGS = ["#AI", "#B2B", "#Marketing", "#ContentMarketing", "#DemandGen", "#SaaS", "#Growth", "#Strategy"]


def make_story(chars: int, paragraphs: int = 3) -> str:
    """Story of `paragraphs` paragraphs totalling exactly `chars` characters (breaks included)."""
    body = chars - 2 * (paragraphs - 1)
    sizes = [body // paragraphs] * paragraphs
    sizes[-1] += body - sum(sizes)
    sentence = "Teams that test small AI pilots learn faster than teams that wait. "

    def para(size: int) -> str:
        text = (sentence * (size // len(sentence) + 1))[: size - 1]
        return (text[:-1] + "s" if text.endswith(" ") else text) + "."

    return "\n\n".join(para(s) for s in sizes)


def linkedin_draft(total: int = 1450, tags: list[str] | None = None, **kwargs) -> LinkedInDraft:
    """A draft whose assembled post (hook through hashtags) is exactly `total` characters."""
    tags = TAGS if tags is None else tags
    fields = {"hook": HOOK, "cta": CTA, "hashtags": tags, "source_numbers": [1, 2]}
    fields.update(kwargs)
    fixed = len(fields["hook"]) + len(fields["cta"]) + len(" ".join(tags)) + 3 * 2  # 3 breaks
    fields.setdefault("story", make_story(total - fixed))
    return LinkedInDraft(**fields)


def make_linkedin(
    hook: str = HOOK,
    story: str | None = None,
    cta: str = CTA,
    tags: list[str] | None = None,
    urls: list[str] | None = None,
    total: int = 1450,
) -> str:
    tags = TAGS if tags is None else tags
    if story is None:
        story = make_story(total - len(hook) - len(cta) - len(" ".join(tags)) - 6)
    urls = [s["url"] for s in SOURCES] if urls is None else urls
    listed = "\n".join(f"- {u}" for u in urls)
    return f"{hook}\n\n{story}\n\n{cta}\n\n{' '.join(tags)}\n\nSources:\n{listed}\n"


def test_linkedin_fixture_is_valid_and_exact_length():
    post = make_linkedin()
    assert len(linkedin_post_text(post)) == 1450
    assert linkedin_source_urls(post) == [s["url"] for s in SOURCES]
    assert hashtags(linkedin_post_text(post)) == TAGS
    assert validate_linkedin(post, SOURCES) == []


@pytest.mark.parametrize(("total", "ok"), [(1299, False), (1300, True), (1600, True), (1601, False)])
def test_linkedin_length_bounds_exclude_sources(total, ok):
    many = [{"title": "x", "url": f"https://example.com/{i}" + "x" * 200, "snippet": ""} for i in range(5)]
    post = make_linkedin(total=total, urls=[s["url"] for s in many])
    failures = validate_linkedin(post, many)
    assert (failures == []) == ok
    if not ok:
        assert f"The post is {total} characters" in failures[0]


@pytest.mark.parametrize(("n", "ok"), [(7, False), (8, True), (12, True), (13, False)])
def test_linkedin_hashtag_count(n, ok):
    tags = [f"#Tag{i}" for i in range(n)]
    failures = validate_linkedin(make_linkedin(tags=tags), SOURCES)
    assert (failures == []) == ok
    if not ok:
        assert failures == [f"The post has {n} unique hashtags; it needs 8-12."]


def test_linkedin_repeated_hashtag_fails():
    failures = validate_linkedin(make_linkedin(tags=TAGS + ["#ai"]), SOURCES)
    assert "The hashtags must not repeat." in failures


def test_linkedin_missing_hashtag_line_fails():
    post = make_linkedin(tags=["#AI", "and", "words"])
    assert "The post must end with one line of hashtags only (before Sources)." in validate_linkedin(post, SOURCES)


def test_linkedin_needs_hook_story_cta():
    post = f"{HOOK}\n\n{CTA}\n\n{' '.join(TAGS)}\n\nSources:\n- {SOURCES[0]['url']}\n"
    failures = validate_linkedin(post, SOURCES)
    assert any("hook, at least one story paragraph and a CTA" in f for f in failures)


def test_linkedin_long_hook_fails():
    hook = "A" * 211
    failures = validate_linkedin(make_linkedin(hook=hook), SOURCES)
    assert failures == ["The hook is 211 characters; it must be at most 210."]


def test_linkedin_hashtag_in_prose_fails():
    failures = validate_linkedin(make_linkedin(cta=CTA[:-1] + " #AI"), SOURCES)
    assert "Hashtags belong only on the final hashtag line, not in the hook, story or CTA." in failures


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ("Teams win [1].", "The post must not contain [n] citation markers."),
        ("## Heading", "The post must be plain text (no markdown headings or bold)."),
        ("**Bold** claim.", "The post must be plain text (no markdown headings or bold)."),
    ],
)
def test_linkedin_citations_and_markdown_fail(bad, message):
    # The hook keeps the fixture's length so only the rule under test fails.
    post = make_linkedin(hook=bad, total=1450 + len(bad) - len(HOOK))
    assert validate_linkedin(post, SOURCES) == [message]


def test_linkedin_multiline_hashtag_block_fails():
    post = make_linkedin(tags=[*TAGS[:4], "\n" + TAGS[4], *TAGS[5:]])
    assert "The post must end with one line of hashtags only (before Sources)." in validate_linkedin(post, SOURCES)


def test_linkedin_sources_needs_blank_line_and_url_lines():
    post = make_linkedin().replace("\n\nSources:", "\nSources:") + "see above\n"
    failures = validate_linkedin(post, SOURCES)
    assert "A blank line must separate the post from 'Sources:'." in failures
    assert "Every line under Sources must be '- <url>'." in failures


@pytest.mark.parametrize(
    ("urls", "message"),
    [
        ([], "The Sources list has 0 URLs; it needs 1-5."),
        (["https://example.com/1"] * 2, "The Sources list must not repeat a URL."),
        (["https://made-up.example"], "Source URL(s) not from the research: https://made-up.example."),
    ],
)
def test_linkedin_sources_rules(urls, message):
    assert message in validate_linkedin(make_linkedin(urls=urls), SOURCES)


def test_linkedin_too_many_sources():
    many = [{"title": "x", "url": f"https://example.com/{i}", "snippet": ""} for i in range(6)]
    post = make_linkedin(urls=[s["url"] for s in many])
    assert validate_linkedin(post, many) == ["The Sources list has 6 URLs; it needs 1-5."]


def test_linkedin_missing_sources_block():
    post = make_linkedin().split("\n\nSources:")[0]
    assert validate_linkedin(post, SOURCES) == ["The post must end with a 'Sources:' list of URLs."]


@pytest.mark.parametrize(
    ("cite", "ok"),
    [
        ("", False),  # no inline citations at all (the live 2026-10-10 case)
        ("[1]", False),  # enough markers, but only one source
        ("[1][2]", True),
    ],
)
def test_body_must_cite_sources_inline(cite, ok):
    body = make_body(KEYWORD, cite=cite) if cite else make_body(KEYWORD, cite="").replace(" .", ".")
    failures = validate_blog(make_post(body=body), SOURCES, KEYWORD)
    cite_failures = [f for f in failures if "inline citation" in f]
    assert (cite_failures == []) == ok
    if not ok:
        assert "needs at least 5 citations to at least 2 different sources" in cite_failures[0]


def test_one_source_needs_only_one_distinct_source():
    one_source = SOURCES[:1]
    post = make_post(body=make_body(KEYWORD, cite="[1]"), sources=one_source)
    assert not any("inline citation" in f for f in validate_blog(post, one_source, KEYWORD))


@pytest.mark.parametrize(
    ("words", "markers", "ok"),
    [(1000, 4, False), (1000, 5, True), (1400, 6, False), (1400, 7, True), (800, 3, False), (800, 4, True), (500, 2, False), (500, 3, True)],
)
def test_citation_minimum_boundary(words, markers, ok):
    # Citation markers don't count as words, so the body stays exactly `words` long.
    mentions = max(1, round(1.5 * words / 100 / 3))
    body = make_body(KEYWORD, total_words=words, mentions=mentions, cite="").replace(" .", ".")
    body += "\n\n" + " ".join(f"[{1 + i % 2}]" for i in range(markers))
    failures = [f for f in validate_blog(make_post(body=body), SOURCES, KEYWORD) if "inline citation" in f]
    assert (failures == []) == ok
