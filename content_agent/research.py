"""Deep Research agent: query generation, SerpAPI search, cited synthesis."""

from __future__ import annotations

import os
import re

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
NO_FINDINGS_LINE = "No findings could be tied to a listed source."

QUERY_PROMPT = """You are a research strategist. Write exactly {n} distinct Google search
queries that together give broad, current, factual coverage of the topic below
(e.g. overview, recent trends/statistics, practical examples or expert views).

Topic: {topic}
"""

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


def generate_queries(state: ContentState) -> dict:
    node = "generate_queries"
    topic = _topic(state)
    # Every run that reaches research overwrites all research fields, even on failure.
    reset = {"queries": [], "sources": [], "findings": Findings(summary="", key_findings=[])}
    try:
        structured = llm.get_llm().with_structured_output(QueryPlan)
        plan = structured.invoke(QUERY_PROMPT.format(n=NUM_QUERIES, topic=topic))
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
    for query in state.get("queries") or []:
        try:
            results = serpapi_search(query, api_key)
        except Exception as exc:  # per-query isolation: one failure must not sink the run
            errors.append(_search_error(query, exc, api_key))
            continue
        for r in (results or [])[:RESULTS_PER_QUERY]:
            url = (r.get("link") or "").strip()
            if not url or url in seen:
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


def _render(topic: str, findings: Findings, sources: list[Source], errors: list[str]) -> str:
    """Interim ending until the report formatter (entry 3) replaces it."""
    parts = [f"## Research: {topic}", findings["summary"]]
    if sources:
        bullets = findings["key_findings"] or [NO_FINDINGS_LINE]
        parts.append("### Key findings\n" + "\n".join(f"- {f}" for f in bullets))
        parts.append(
            "### Sources\n"
            + "\n".join(f"{i}. {s['title']} — {s['url']}" for i, s in enumerate(sources, 1))
        )
    if errors:
        parts.append("### Search problems\n" + "\n".join(f"- {e}" for e in errors))
    return "\n\n".join(parts)


def synthesize(state: ContentState) -> dict:
    node = "synthesize"
    sources = list(state.get("sources") or [])
    errors = list(state.get("errors") or [])
    topic = _topic(state)

    if not sources:  # nothing to synthesize: no LLM call
        findings = Findings(summary=NO_SOURCES_SUMMARY, key_findings=[])
        return {"findings": findings, "final_output": _render(topic, findings, [], errors)}

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
    findings = Findings(summary=summary, key_findings=key_findings)
    return {"findings": findings, "final_output": _render(topic, findings, sources, errors)}
