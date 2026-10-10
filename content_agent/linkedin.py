"""LinkedIn Writer: turns Deep Research findings into a plain-text LinkedIn post.

The LLM writes hook, story, CTA, hashtags and the source numbers it relied on; code strips
citation markers and markdown, normalizes hashtags, assembles the post and its Sources list,
then checks it with validators.validate_linkedin and asks the LLM to revise (up to
MAX_REVISIONS times) until it passes.
"""

from __future__ import annotations

import re

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, Field

from content_agent import llm
from content_agent.research import _LLM_ERRORS, _clean_citations, _llm_failure, _topic
from content_agent.state import ContentState
from content_agent.validators import (
    HASHTAGS_MAX,
    HASHTAGS_MIN,
    HOOK_MAX,
    LINKEDIN_MAX,
    LINKEDIN_MIN,
    LINKEDIN_SOURCES_HEADING,
    LINKEDIN_SOURCES_MAX,
    linkedin_post_text,
    validate_linkedin,
)

NODE_NAME = "linkedin_writer"
MAX_REVISIONS = 2
TARGET_CHARS = 1450
FALLBACK_SOURCES = 3

WRITE_PROMPT = """You are a LinkedIn ghostwriter for B2B marketers. Using ONLY the research
below, write a LinkedIn post about: {topic}

Return:
- hook: one or two punchy sentences that make people stop scrolling, at most {hook_max}
  characters. Plain text.
- story: 3-5 short paragraphs (separated by a blank line) that tell the story behind the
  research: a situation, the surprising data points, and the lesson. Plain text, short
  sentences, no bullet symbols other than simple line breaks.
- cta: one sentence that invites readers to act or comment (e.g. a question).
- hashtags: {tags_min}-{tags_max} relevant hashtags (single words or CamelCase, no spaces).
- source_numbers: the numbers of the sources below that the post relies on (1-{sources_max}).

Rules:
- The whole post (hook + story + cta + hashtags) must be {min_chars}-{max_chars} characters;
  aim for about {target} characters.
- LinkedIn shows plain text: no markdown (no '#' headings, no '**' bold), no hashtags
  outside the hashtags field, and NO citation markers like [1] in the text.
- Do not add facts that are not supported by the research.

Research summary:
{summary}

Key findings:
{key_findings}

Sources:
{sources}
"""

REVISION_PROMPT = """{brief}

----------------------------------------------------------------------
You already wrote a draft for this brief, shown below. It FAILED these checks:
{failures}

Length: the post (hook through hashtags, excluding Sources) is {length} characters; the
target is about {target}, so {length_action}.

Previous draft
--------------
hook: {hook}

story:
{story}

cta: {cta}

hashtags: {hashtags}

----------------------------------------------------------------------
Now return a REVISED draft (hook, story, cta, hashtags, source_numbers) that fixes every
failed check while keeping all the rules above and the content accurate. Do not return the
previous draft unchanged. Change the length mainly by adding or cutting story sentences.
"""


class LinkedInDraft(BaseModel):
    hook: str = Field(description=f"Scroll-stopping opening, at most {HOOK_MAX} characters.")
    story: str = Field(description="Story paragraphs separated by blank lines, plain text.")
    cta: str = Field(description="One call-to-action sentence.")
    hashtags: list[str] = Field(description=f"{HASHTAGS_MIN}-{HASHTAGS_MAX} hashtags.")
    source_numbers: list[int] = Field(
        default_factory=list, description="Numbers of the sources the post relies on."
    )


_INLINE_TAG = re.compile(r"(?<![\w#])#(\w+)")
_MD_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+")


def _clean_line(line: str) -> str:
    line = _MD_HEADING.sub("", line).replace("**", "")
    line = _INLINE_TAG.sub(r"\1", line)  # hashtags only on the hashtag line
    return _clean_citations(line, 0)  # a LinkedIn post carries no [n] markers


def _clean_paragraph(text: str) -> str:
    """One paragraph: cleaned lines joined with spaces."""
    return " ".join(x for x in (_clean_line(line) for line in (text or "").splitlines()) if x)


def _clean_story(text: str) -> str:
    """Cleaned story, keeping its paragraph breaks."""
    text = "\n".join(_clean_line(line) for line in (text or "").splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _normalize_tags(tags: list[str]) -> list[str]:
    """One leading '#', word characters only, case-insensitive dedupe, at most HASHTAGS_MAX."""
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags or []:
        word = re.sub(r"\W", "", tag or "")
        if word and word.lower() not in seen:
            seen.add(word.lower())
            out.append(f"#{word}")
    return out[:HASHTAGS_MAX]


def _source_urls(numbers: list[int], sources: list) -> list[str]:
    """URLs of the named sources (valid, deduped, in source order, capped); else the first few."""
    picked = sorted({n for n in numbers or [] if 1 <= n <= len(sources)})[:LINKEDIN_SOURCES_MAX]
    if not picked:
        picked = list(range(1, min(FALLBACK_SOURCES, len(sources)) + 1))
    return [sources[n - 1]["url"] for n in picked]


def _assemble(draft: LinkedInDraft, sources: list) -> str:
    parts = [
        _clean_paragraph(draft.hook),
        _clean_story(draft.story),
        _clean_paragraph(draft.cta),
        " ".join(_normalize_tags(draft.hashtags)),
    ]
    post = "\n\n".join(p for p in parts if p)
    listed = "\n".join(f"- {u}" for u in _source_urls(draft.source_numbers, sources))
    return f"{post}\n\n{LINKEDIN_SOURCES_HEADING}\n{listed}\n"


def _draft_failures(draft: LinkedInDraft) -> list[str]:
    """Parts the validator cannot see: it finds hook and CTA by position, so an empty one
    would let a story paragraph stand in for it."""
    return [
        f"The {name} is empty."
        for name, value in (("hook", _clean_paragraph(draft.hook)), ("cta", _clean_paragraph(draft.cta)))
        if not value
    ]


def _length_action(length: int) -> str:
    if length < LINKEDIN_MIN:
        return f"add about {TARGET_CHARS - length} characters"
    if length > LINKEDIN_MAX:
        return f"cut about {length - TARGET_CHARS} characters"
    return "keep about the same length"


def _invoke(prompt: str, temperature: float) -> LinkedInDraft:
    structured = llm.get_llm(temperature=temperature).with_structured_output(LinkedInDraft)
    draft = structured.invoke(prompt)
    if not isinstance(draft, LinkedInDraft):
        raise OutputParserException("structured output did not match LinkedInDraft")
    return draft


def linkedin_writer(state: ContentState) -> dict:
    topic = _topic(state)
    sources = list(state.get("sources") or [])
    findings = state.get("findings") or {}
    brief = WRITE_PROMPT.format(
        topic=topic,
        hook_max=HOOK_MAX,
        tags_min=HASHTAGS_MIN,
        tags_max=HASHTAGS_MAX,
        sources_max=LINKEDIN_SOURCES_MAX,
        min_chars=LINKEDIN_MIN,
        max_chars=LINKEDIN_MAX,
        target=TARGET_CHARS,
        summary=findings.get("summary") or "",
        key_findings="\n".join(f"- {k}" for k in findings.get("key_findings") or []) or "(none)",
        sources="\n\n".join(
            f"[{i}] {s['title']}\nURL: {s['url']}\n{s['snippet']}" for i, s in enumerate(sources, 1)
        ),
    )

    # Only the LLM call sits in the try: errors in our own code must not read as model errors.
    try:
        draft = _invoke(brief, 0.5)
    except _LLM_ERRORS as exc:
        return _llm_failure(state, NODE_NAME, exc)
    post = _assemble(draft, sources)
    failures = _draft_failures(draft) + validate_linkedin(post, sources)
    for _ in range(MAX_REVISIONS):
        if not failures:
            break
        length = len(linkedin_post_text(post))
        prompt = REVISION_PROMPT.format(
            brief=brief,
            failures="\n".join(f"- {f}" for f in failures),
            length=length,
            target=TARGET_CHARS,
            length_action=_length_action(length),
            hook=draft.hook,
            story=draft.story,
            cta=draft.cta,
            hashtags=" ".join(draft.hashtags),
        )
        try:
            draft = _invoke(prompt, 0.2)  # revisions should follow the fix instructions closely
        except _LLM_ERRORS as exc:
            return _llm_failure(state, NODE_NAME, exc)
        post = _assemble(draft, sources)
        failures = _draft_failures(draft) + validate_linkedin(post, sources)

    result: dict = {"final_output": post}
    if failures:  # still invalid: the last draft is the output, each failed check is recorded
        result["errors"] = list(state.get("errors") or []) + [
            f"{NODE_NAME}: LinkedIn check failed: {f}" for f in failures
        ]
    return result
