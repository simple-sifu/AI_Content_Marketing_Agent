"""Deep Research agent: query generation, SerpAPI search, cited synthesis."""

from __future__ import annotations

import math
import os
import re
from datetime import date

import openai
from langchain_core.exceptions import OutputParserException
from langchain_openai.chat_models.base import OpenAIRefusalError
from pydantic import BaseModel, Field

from content_agent import llm
from content_agent.state import ContentState, Findings, Source

NUM_QUERIES = 3
RESULTS_PER_QUERY = 5
# Per-request timeout; the client's default is 60000 seconds, which would hang the run.
SEARCH_TIMEOUT_SECONDS = 30
MISSING_SERPAPI_KEY = (
    "SERPAPI_API_KEY is not set. Add it to your .env file to enable web research."
)
NO_SOURCES_SUMMARY = "No sources were found for this topic, so no findings can be reported."
UNCITED_SUMMARY = "See the cited key findings below."
# Key Findings placeholder in the report when no finding survived citation cleaning.
NO_FINDINGS_LINE = "No findings could be tied to a listed source."

QUERY_PROMPT = """You are a research strategist. Write exactly {n} distinct Google search
queries that together give broad, current, factual coverage of the topic below
(e.g. overview, recent trends/statistics, practical examples or expert views).

Today's date is {today}. For time-sensitive queries (trends, statistics, forecasts) use the
current year; never put a past year in a query unless the topic itself names one.

Topic: {topic}
"""

# Words that say nothing about relevance; the rest of the topic must show up in a result.
_STOPWORDS = frozenset("a an and the of in on for to with about how what vs".split())
_EDGE_PUNCTUATION = ".,;:!?\"'()[]{}"

SYNTHESIS_PROMPT = """You are a research analyst. Using ONLY the numbered sources below,
write a research synthesis about: {topic}

Rules:
- Every factual claim must end with one or more citations like [1] or [2][3],
  referring to the source numbers below. Never cite a number that is not listed.
- Do not add facts that are not supported by the sources.
- summary: 2-4 sentences, cited.
- key_findings: 3-7 concise bullet-style findings, each cited.

Sources:
{sources}
"""

_CITATION = re.compile(r"\[(\d+)\]")
# Same set the Query Handler catches; ValueError covers OutputParserException and
# pydantic.ValidationError.
_LLM_ERRORS = (openai.OpenAIError, ValueError, OpenAIRefusalError)


class QueryPlan(BaseModel):
    queries: list[str] = Field(description=f"Exactly {NUM_QUERIES} Google search queries.")


class Synthesis(BaseModel):
    summary: str = Field(description="Short cited executive summary.")
    key_findings: list[str] = Field(description="Cited key findings.")


class SerpAPIError(RuntimeError):
    """An error SerpAPI reported in-band (quota, auth, bad request)."""


def _topic(state: ContentState) -> str:
    return (state.get("topic") or state.get("request") or "").strip()


def _llm_failure(state: ContentState, node: str, exc: Exception) -> dict:
    """Entry 1's convention: intent=error, readable message, class-name-only error entry."""
    return {
        "intent": "error",
        "final_output": llm.llm_error(node, exc),
        "errors": list(state.get("errors") or []) + [f"{node}: {type(exc).__name__}"],
    }


def _pad_queries(candidates: list[str], topic: str) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for q in [*candidates, topic, f"{topic} trends", f"{topic} statistics"]:
        q = " ".join((q or "").split())
        if q and q.lower() not in seen:
            seen.add(q.lower())
            queries.append(q)
        if len(queries) == NUM_QUERIES:
            break
    return queries


def _today() -> str:
    """Today's date (ISO); a function so tests can pin it."""
    return date.today().isoformat()


def topic_keywords(topic: str) -> list[str]:
    """Lowercase topic words minus stopwords; internal punctuation stays (b2b, node.js, c++)."""
    words = (w.strip(_EDGE_PUNCTUATION) for w in (topic or "").lower().split())
    words = (re.sub(r"['’]s$", "", w) for w in words)  # possessive: "AI's" -> "ai"
    return list(dict.fromkeys(w for w in words if w and w not in _STOPWORDS))


def _keyword_pattern(keyword: str) -> str:
    """Whole-word match; a hyphenated keyword also matches with a space ("ai-powered" ~ "AI powered")."""
    parts = [re.escape(x) for x in keyword.split("-") if x]
    return r"(?<!\w)" + r"[\s\-]+".join(parts) + r"(?!\w)"


def _on_topic(result: dict, keywords: list[str]) -> bool:
    """At least half the topic keywords appear as whole words in the title or snippet."""
    if not keywords:
        return True
    text = f"{result.get('title') or ''} {result.get('snippet') or ''}".lower()
    hits = sum(1 for k in keywords if re.search(_keyword_pattern(k), text))
    return hits >= math.ceil(len(keywords) / 2)


def generate_queries(state: ContentState) -> dict:
    node = "generate_queries"
    topic = _topic(state)
    # Every run that reaches research overwrites all research fields, even on failure.
    reset = {"queries": [], "sources": [], "findings": Findings(summary="", key_findings=[])}
    try:
        structured = llm.get_llm().with_structured_output(QueryPlan)
        plan = structured.invoke(QUERY_PROMPT.format(n=NUM_QUERIES, topic=topic, today=_today()))
        if not isinstance(plan, QueryPlan):
            raise OutputParserException("structured output did not match QueryPlan")
    except _LLM_ERRORS as exc:
        return {**reset, **_llm_failure(state, node, exc)}

    return {**reset, "queries": _pad_queries(list(plan.queries or []), topic)}


def serpapi_search(query: str, api_key: str) -> list[dict]:
    """Run one Google search through SerpAPI and return its organic results.

    The single SerpAPI call site (tests patch it)."""
    from serpapi import GoogleSearch

    search = GoogleSearch({"q": query, "api_key": api_key, "num": RESULTS_PER_QUERY})
    search.timeout = SEARCH_TIMEOUT_SECONDS  # __init__ takes no timeout; a timeout raises per query
    data = search.get_dict()
    if data.get("error"):
        # "Hasn't returned any results" is an empty result set, not a failure.
        if "hasn't returned any results" in str(data["error"]).lower():
            return []
        raise SerpAPIError(str(data["error"]))
    return data.get("organic_results", []) or []


def _search_error(query: str, exc: Exception, api_key: str) -> str:
    if isinstance(exc, SerpAPIError):
        detail = str(exc).replace(api_key, "***")
        return f"Search failed for {query!r}: SerpAPI error: {detail}"
    # Raw exception text can embed the request URL (api_key=<key>): class name only.
    return f"Search failed for {query!r}: {type(exc).__name__}"


def run_searches(state: ContentState) -> dict:
    errors = list(state.get("errors") or [])
    api_key = (os.getenv("SERPAPI_API_KEY") or "").strip()
    if not api_key:
        return {"sources": [], "errors": errors + [MISSING_SERPAPI_KEY]}

    sources: list[Source] = []
    seen: set[str] = set()
    keywords = topic_keywords(_topic(state))
    for query in state.get("queries") or []:
        try:
            results = serpapi_search(query, api_key)
        except Exception as exc:  # per-query isolation: one failure must not sink the run
            errors.append(_search_error(query, exc, api_key))
            continue
        for r in (results or [])[:RESULTS_PER_QUERY]:
            url = (r.get("link") or "").strip()
            # Off-topic results (e.g. "Case IH" for a "case studies" query) never become sources.
            if not url or url in seen or not _on_topic(r, keywords):
                continue
            seen.add(url)
            sources.append(
                Source(
                    # Brackets in a title would read as a citation marker like [2025].
                    title=" ".join((r.get("title") or url).split())
                    .replace("[", "(")
                    .replace("]", ")"),
                    url=url,
                    snippet=(r.get("snippet") or "").strip(),
                )
            )
    return {"sources": sources, "errors": errors}


def _clean_citations(text: str, n_sources: int) -> str:
    """Drop citation markers that do not map to a listed source."""
    cleaned = _CITATION.sub(
        lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_sources else "", text
    )
    cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _has_citation(text: str) -> bool:
    return bool(_CITATION.search(text))


def synthesize(state: ContentState) -> dict:
    node = "synthesize"
    sources = list(state.get("sources") or [])
    topic = _topic(state)

    if not sources:  # nothing to synthesize: no LLM call
        return {"findings": Findings(summary=NO_SOURCES_SUMMARY, key_findings=[])}

    numbered = "\n\n".join(
        f"[{i}] {s['title']}\nURL: {s['url']}\n{s['snippet']}" for i, s in enumerate(sources, 1)
    )
    try:
        structured = llm.get_llm().with_structured_output(Synthesis)
        result = structured.invoke(SYNTHESIS_PROMPT.format(topic=topic, sources=numbered))
        if not isinstance(result, Synthesis):
            raise OutputParserException("structured output did not match Synthesis")
    except _LLM_ERRORS as exc:
        return _llm_failure(state, node, exc)

    n = len(sources)
    summary = _clean_citations(result.summary or "", n)
    if not _has_citation(summary):  # an uncited summary is unsupported by search
        summary = UNCITED_SUMMARY
    # A finding that cites nothing valid is unsupported by search: drop it.
    key_findings = [
        f for f in (_clean_citations(k or "", n) for k in result.key_findings or []) if _has_citation(f)
    ]
    return {"findings": Findings(summary=summary, key_findings=key_findings)}
