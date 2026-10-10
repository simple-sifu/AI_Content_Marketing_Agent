"""SEO checks for blog posts: the one definition of "valid" for the writer, tests and live check.

A post looks like:

    ---
    meta_description: "..."
    ---

    # Title

    <body with ## and ### sections, cited [n]>

    ## Sources

    1. [title](url)

The *body* is everything between the H1 line and the final `## Sources` heading; word
count and keyword density are measured on it alone so front matter and Sources don't skew them.
"""

from __future__ import annotations

import json
import math
import re

from content_agent.research import _CITATION

META_MIN, META_MAX = 120, 160
MIN_BODY_WORDS = 800
DENSITY_MIN, DENSITY_MAX = 1.0, 2.0
SOURCES_HEADING = "## Sources"

_WORD = re.compile(r"\w+(?:['’]\w+)*")
_H1 = re.compile(r"^# \S")
_H2 = re.compile(r"^## \S")
_H3 = re.compile(r"^### \S")
_META = re.compile(r"^meta_description:[ \t]*(.*)$", re.MULTILINE)


def _split(post: str) -> tuple[str | None, str]:
    """Return (front matter or None, rest of the post)."""
    text = (post or "").lstrip("﻿")
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            after = text.find("\n", end + 1)
            rest = "" if after == -1 else text[after + 1 :]
            return text[4:end], rest
    return None, text


def _sources_index(lines: list[str]) -> int:
    """Index of the last `## Sources` heading line, or len(lines) when there is none."""
    found = [i for i, line in enumerate(lines) if line.strip() == SOURCES_HEADING]
    return found[-1] if found else len(lines)


def _body_and_sources(rest: str) -> tuple[str, str | None]:
    """Split the post (after front matter) into body and the Sources section."""
    lines = rest.splitlines()
    h1 = next((i for i, line in enumerate(lines) if _H1.match(line)), -1)
    src = _sources_index(lines)
    start = h1 + 1
    if src == len(lines) or src < start:
        return "\n".join(lines[start:]), None
    return "\n".join(lines[start:src]), "\n".join(lines[src + 1 :])


def meta_description(post: str) -> str | None:
    front, _ = _split(post)
    if front is None:
        return None
    m = _META.search(front)
    if not m:
        return None
    raw = m.group(1).strip()
    if raw.startswith('"'):
        try:
            return str(json.loads(raw))
        except ValueError:
            return raw.strip('"')
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1].replace("''", "'")
    return raw


def blog_body(post: str) -> str:
    """Body text: after the H1, before `## Sources`, excluding front matter."""
    _, rest = _split(post)
    return _body_and_sources(rest)[0]


def count_words(text: str) -> int:
    return len(_WORD.findall(_CITATION.sub(" ", text or "")))


def body_words(post: str) -> int:
    return count_words(blog_body(post))


def phrase_words(keyword: str) -> int:
    """Number of words in the keyword phrase (the density formula's multiplier)."""
    return len(_WORD.findall(keyword or ""))


def keyword_mentions(text: str, keyword: str) -> int:
    """Case-insensitive whole-phrase matches of `keyword` in `text`."""
    # Split on whitespace/hyphens only, so punctuation inside a token ("Node.js", "vs.",
    # "C++") must match verbatim.
    tokens = [t for t in re.split(r"[\s\-]+", (keyword or "").strip()) if t]
    if not tokens:
        return 0
    pattern = r"(?<!\w)" + r"[\s\-]+".join(re.escape(t) for t in tokens) + r"(?!\w)"
    return len(re.findall(pattern, _CITATION.sub(" ", text or ""), flags=re.IGNORECASE))


def keyword_density(post: str, keyword: str) -> float:
    """Mentions x words in the phrase / body words x 100, measured on the body only."""
    body = blog_body(post)
    words = count_words(body)
    if not words:
        return 0.0
    return keyword_mentions(body, keyword) * phrase_words(keyword) / words * 100


def validate_blog(post: str, sources: list, keyword: str) -> list[str]:
    """Return every failed SEO check as a readable message; an empty list means valid."""
    failures: list[str] = []
    front, rest = _split(post)

    meta = meta_description(post)
    if front is None:
        failures.append("The post must start with YAML front matter (--- ... ---).")
    elif meta is None:
        failures.append("The front matter must contain meta_description.")
    elif not META_MIN <= len(meta) <= META_MAX:
        failures.append(
            f"meta_description is {len(meta)} characters; it must be {META_MIN}-{META_MAX}."
        )

    lines = rest.splitlines()
    h1_count = sum(1 for line in lines if _H1.match(line))
    if h1_count != 1:
        failures.append(f"The post must have exactly one '# ' H1 title; found {h1_count}.")

    body, sources_section = _body_and_sources(rest)
    body_lines = body.splitlines()
    h2 = sum(1 for line in body_lines if _H2.match(line))
    h3 = sum(1 for line in body_lines if _H3.match(line))
    if h2 < 2:
        failures.append(f"The body needs at least two '## ' sections; found {h2}.")
    if h3 < 1:
        failures.append("The body needs at least one '### ' subsection; found 0.")

    words = count_words(body)
    if words < MIN_BODY_WORDS:
        failures.append(f"The body has {words} words; it needs at least {MIN_BODY_WORDS}.")

    tokens = _WORD.findall(keyword or "")
    if not tokens:
        failures.append("No primary keyword was given, so keyword density cannot be checked.")
    else:
        mentions = keyword_mentions(body, keyword)
        density = keyword_density(post, keyword)
        if not DENSITY_MIN <= density <= DENSITY_MAX:
            k = len(tokens)
            lo = max(1, math.ceil(DENSITY_MIN * words / 100 / k))
            hi = max(lo, math.floor(DENSITY_MAX * words / 100 / k))
            failures.append(
                f"Keyword '{keyword}' density is {density:.2f}% ({mentions} exact-phrase "
                f"mentions in {words} body words); it must be "
                f"{DENSITY_MIN:g}-{DENSITY_MAX:g}%, i.e. {lo}-{hi} mentions at this length."
            )

    n = len(sources or [])
    # Every marker outside the Sources list (front matter, title, body) must map to a source.
    cited = "\n".join([front or "", *lines[: _sources_index(lines)]])
    bad = sorted({int(m) for m in _CITATION.findall(cited) if not 1 <= int(m) <= n})
    if bad:
        listed = ", ".join(f"[{b}]" for b in bad)
        failures.append(f"Citation(s) {listed} do not map to a listed source (1-{n}).")

    if sources_section is None:
        failures.append(f"The post must end with a '{SOURCES_HEADING}' section.")
    else:
        expected = [f"{i}. [{s['title']}]({s['url']})" for i, s in enumerate(sources or [], 1)]
        actual = [line.strip() for line in sources_section.splitlines() if line.strip()]
        if actual != expected:
            failures.append(
                f"The Sources section must list the {n} sources as 'n. [title](url)' in order."
            )
    return failures
