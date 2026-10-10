"""SEO Blog Writer: turns Deep Research findings into a long-form, cited markdown post.

The LLM writes title, meta description and body; code assembles the front matter, H1,
demoted body and Sources list, then checks the post with validators.validate_blog and
asks the LLM to revise (up to MAX_REVISIONS times) until it passes.
"""

from __future__ import annotations

import json
import math
import re

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, Field

from content_agent import llm
from content_agent.research import _LLM_ERRORS, _clean_citations, _llm_failure, _topic
from content_agent.state import ContentState
from content_agent.strategist import _clean_title, _unbracket
from content_agent.validators import (
    DENSITY_MAX,
    DENSITY_MIN,
    META_MAX,
    META_MIN,
    SOURCES_HEADING,
    blog_body,
    count_words,
    keyword_mentions,
    phrase_words,
    validate_blog,
)

NODE_NAME = "blog_writer"
MAX_REVISIONS = 2
TARGET_WORDS = (1200, 1600)

WRITE_PROMPT = """You are an SEO content writer. Using ONLY the research below, write a
long-form blog post for a marketing audience.

Primary keyword (exact phrase): "{keyword}"

Return:
- title: a compelling title that contains the primary keyword (plain text, no markdown,
  no citations).
- meta_description: {meta_min}-{meta_max} characters, plain text, includes the primary
  keyword, no citations.
- body: the post body in markdown, {min_words}-{max_words} words. Do NOT include the
  title, any '# ' H1 heading, or a Sources/References section (they are added for you).
  Use at least two '## ' sections and at least one '### ' subsection. To reach the
  length, write an introduction plus 6-8 '## ' sections, each with 2-3 paragraphs of
  4-6 sentences, and a conclusion.

Body rules:
- Keyword budget: the exact phrase "{keyword}" may appear only {lo}-{hi} times in the
  whole body, headings included: once in the introduction, in at most ONE heading, and
  a few times elsewhere. Every other heading and sentence must refer to the subject with
  synonyms or pronouns (e.g. "these tools", "this approach") instead. Overusing the
  phrase fails the SEO check; count your uses before answering.
- Every factual claim must end with one or more citations like [1] or [2][3],
  referring to the source numbers below. Never cite a number that is not listed.
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
You already wrote a draft for this brief, shown below. It FAILED these SEO checks:
{failures}

{keyword_usage}

Previous draft
--------------
title: {title}
meta_description: {meta}
body:
{body}

----------------------------------------------------------------------
Now return a REVISED draft (title, meta_description and body) that fixes every failed
check while keeping all the rules above and the content and citations accurate. Do not
return the previous draft unchanged.

How to fix common failures:
- Keyword density: follow the keyword usage target above exactly; it replaces the
  keyword budget in the brief (the phrase may then appear in more than one heading). To remove a mention,
  reword that line with a synonym or pronoun (e.g. "these tools", "this approach"); to
  add one, use the exact phrase "{keyword}" in a sentence or heading.
- Too few words: expand each section with more cited detail, examples and practical
  tips; aim for at least {min_words} words, without adding keyword mentions.
- meta_description length: count characters; aim for about 145.
"""


class BlogDraft(BaseModel):
    title: str = Field(description="Post title containing the primary keyword, plain text.")
    meta_description: str = Field(
        description=f"SEO meta description, {META_MIN}-{META_MAX} characters, plain text."
    )
    body: str = Field(description="Markdown body without the H1 title or a Sources section.")


_HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t#]*$")
_SOURCES_LIKE = re.compile(r"^#{1,6}[ \t]+(sources|references|citations)[ \t:]*$", re.IGNORECASE)


def _mention_range(keyword: str) -> tuple[int, int]:
    """Mention budget for the requested length (centred on ~1,400 words): any count in
    [lo, hi] keeps density within 1-2% for a body anywhere in TARGET_WORDS
    (lo reaches 1% at the longest length, hi stays under 2% at the shortest)."""
    k = max(1, phrase_words(keyword))
    lo = max(1, math.ceil(DENSITY_MIN * TARGET_WORDS[1] / 100 / k))
    hi = max(lo, math.floor(DENSITY_MAX * TARGET_WORDS[0] / 100 / k))
    return lo, hi


def _clean_body(body: str, title: str, n_sources: int) -> str:
    """Valid citations only; '#' headings demoted to '##'; no LLM-written title or trailing
    Sources/References section (one mid-body, followed by another heading, is kept)."""
    raw = (body or "").splitlines()
    heads = [i for i, line in enumerate(raw) if _HEADING.match(line)]
    if heads and _SOURCES_LIKE.match(raw[heads[-1]].strip()):
        raw = raw[: heads[-1]]  # the Sources list is built in code; drop the LLM's own
    lines: list[str] = []
    for line in raw:
        m = _HEADING.match(line)
        if m and len(m.group(1)) == 1:
            if not any(x.strip() for x in lines) and _unbracket(_clean_title(m.group(2))) == title:
                continue  # the LLM repeated the title as an H1
            line = f"## {m.group(2)}"
        lines.append(line)
    # Clean per line so markdown line structure (lists, headings) survives.
    cleaned = []
    for line in lines:
        indent = line[: len(line) - len(line.lstrip())]
        cleaned.append(indent + _clean_citations(line, n_sources) if line.strip() else "")
    text = "\n".join(cleaned)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _clean_meta(meta: str) -> str:
    return _unbracket(_clean_citations(" ".join((meta or "").split()), 0))


def _assemble(draft: BlogDraft, topic: str, sources: list) -> str:
    title = _unbracket(_clean_title(draft.title)) or _unbracket(topic)
    body = _clean_body(draft.body, title, len(sources))
    # json.dumps gives a valid YAML double-quoted scalar.
    meta = json.dumps(_clean_meta(draft.meta_description), ensure_ascii=False)
    front = f"---\nmeta_description: {meta}\n---"
    source_list = "\n".join(f"{i}. [{s['title']}]({s['url']})" for i, s in enumerate(sources, 1))
    return f"{front}\n\n# {title}\n\n{body}\n\n{SOURCES_HEADING}\n\n{source_list}\n"


def _sections_without(body: str, keyword: str) -> list[str]:
    """Headings of body sections whose text never uses the exact keyword phrase."""
    sections: list[tuple[str, list[str]]] = []
    for line in body.splitlines():
        m = _HEADING.match(line)
        if m:
            sections.append((m.group(2), []))
        elif sections:
            sections[-1][1].append(line)
    return [h for h, lines in sections if not keyword_mentions("\n".join(lines), keyword)]


def _keyword_usage(post: str, keyword: str) -> str:
    """Where the draft's body uses the exact keyword phrase, and how many uses to aim for."""
    body = blog_body(post)
    lines = [line for line in body.splitlines() if keyword_mentions(line, keyword)]
    total = keyword_mentions(body, keyword)
    k = max(1, phrase_words(keyword))
    # Aim for the middle of the allowed 1-2% at the draft's current length.
    target = max(1, round(1.5 * count_words(body) / 100 / k))
    if total > target:
        action = f"remove {total - target} of them (reword those lines without the phrase)"
    elif total < target:
        empty = _sections_without(body, keyword)[: target - total]
        where = f" (one in each of these sections: {'; '.join(empty)})" if empty else ""
        action = f"add {target - total} more{where}"
    else:
        action = "keep that number"
    listed = "\n".join(f"- {line.strip()[:200]}" for line in lines) or "- (none)"
    return (
        f'Keyword usage: your body uses the exact phrase "{keyword}" {total} times; for its '
        f"length the target is {target}, so {action}. Lines that contain it now:\n{listed}"
    )


def _invoke(prompt: str, temperature: float) -> BlogDraft:
    structured = llm.get_llm(temperature=temperature).with_structured_output(BlogDraft)
    draft = structured.invoke(prompt)
    if not isinstance(draft, BlogDraft):
        raise OutputParserException("structured output did not match BlogDraft")
    return draft


def blog_writer(state: ContentState) -> dict:
    topic = _topic(state)
    sources = list(state.get("sources") or [])
    findings = state.get("findings") or {}
    lo, hi = _mention_range(topic)
    brief = WRITE_PROMPT.format(
        keyword=topic,
        meta_min=META_MIN,
        meta_max=META_MAX,
        min_words=TARGET_WORDS[0],
        max_words=TARGET_WORDS[1],
        lo=lo,
        hi=hi,
        summary=findings.get("summary") or "",
        key_findings="\n".join(f"- {k}" for k in findings.get("key_findings") or []) or "(none)",
        sources="\n\n".join(
            f"[{i}] {s['title']}\nURL: {s['url']}\n{s['snippet']}" for i, s in enumerate(sources, 1)
        ),
    )

    # Only the LLM call sits in the try: errors in our own code must not read as model errors.
    try:
        draft = _invoke(brief, 0.4)
    except _LLM_ERRORS as exc:
        return _llm_failure(state, NODE_NAME, exc)
    post = _assemble(draft, topic, sources)
    failures = validate_blog(post, sources, topic)
    for _ in range(MAX_REVISIONS):
        if not failures:
            break
        prompt = REVISION_PROMPT.format(
            failures="\n".join(f"- {f}" for f in failures),
            keyword=topic,
            min_words=TARGET_WORDS[0],
            keyword_usage=_keyword_usage(post, topic),
            title=draft.title,
            meta=draft.meta_description,
            body=draft.body,
            brief=brief,
        )
        try:
            draft = _invoke(prompt, 0.2)  # revisions should follow the fix instructions closely
        except _LLM_ERRORS as exc:
            return _llm_failure(state, NODE_NAME, exc)
        post = _assemble(draft, topic, sources)
        failures = validate_blog(post, sources, topic)

    result: dict = {"final_output": post}
    if failures:  # still invalid: the last draft is the output, each failed check is recorded
        result["errors"] = list(state.get("errors") or []) + [
            f"{NODE_NAME}: SEO check failed: {f}" for f in failures
        ]
    return result
