"""Deep Research agent: query generation, SerpAPI search, cited synthesis."""

from __future__ import annotations

import os
import re

from pydantic import BaseModel, Field

from content_agent import llm
from content_agent.state import ContentState, Findings, Source

NUM_QUERIES = 3
RESULTS_PER_QUERY = 5
MISSING_SERPAPI_KEY = (
    "SERPAPI_API_KEY is not set. Add it to your .env file to enable web research."
)
NO_SOURCES_SUMMARY = "No sources were found for this topic, so no findings can be reported."
UNCITED_SUMMARY = "See the cited key findings below."

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


class QueryPlan(BaseModel):
    queries: list[str] = Field(description=f"Exactly {NUM_QUERIES} Google search queries.")


class Synthesis(BaseModel):
    summary: str = Field(description="Short cited executive summary.")
    key_findings: list[str] = Field(description="Cited key findings.")


def generate_queries(state: ContentState) -> dict:
    topic = state.get("topic") or state.get("request", "")
    structured = llm.get_llm().with_structured_output(QueryPlan)
    plan: QueryPlan = structured.invoke(QUERY_PROMPT.format(n=NUM_QUERIES, topic=topic))

    queries: list[str] = []
    for q in [*plan.queries, topic, f"{topic} trends", f"{topic} statistics"]:
        q = (q or "").strip()
        if q and q.lower() not in {x.lower() for x in queries}:
            queries.append(q)
        if len(queries) == NUM_QUERIES:
            break
    return {"queries": queries}


def serpapi_search(query: str, api_key: str) -> list[dict]:
    """Run one Google search through SerpAPI and return its organic results."""
    from serpapi import GoogleSearch  # imported lazily; patched in tests

    data = GoogleSearch({"q": query, "api_key": api_key, "num": RESULTS_PER_QUERY}).get_dict()
    if data.get("error"):
        # SerpAPI reports quota/auth problems in-band. "Hasn't returned any results"
        # is not a failure, just an empty result set.
        if "hasn't returned any results" in str(data["error"]).lower():
            return []
        raise RuntimeError(str(data["error"]))
    return data.get("organic_results", []) or []


def run_searches(state: ContentState) -> dict:
    api_key = (os.getenv("SERPAPI_API_KEY") or "").strip()
    if not api_key:
        return {"sources": [], "errors": [MISSING_SERPAPI_KEY]}

    sources: list[Source] = []
    seen: set[str] = set()
    errors: list[str] = []
    for query in state.get("queries", []):
        try:
            results = serpapi_search(query, api_key)
        except Exception as exc:  # per-query isolation: one failure must not sink the run
            detail = str(exc).replace(api_key, "***")  # HTTP errors embed api_key=<key> in the URL
            errors.append(f"Search failed for {query!r}: {type(exc).__name__}: {detail}")
            continue
        for r in results[:RESULTS_PER_QUERY]:
            url = (r.get("link") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append(
                {
                    "title": (r.get("title") or url).strip(),
                    "url": url,
                    "snippet": (r.get("snippet") or "").strip(),
                }
            )
    return {"sources": sources, "errors": errors}


def _clean_citations(text: str, n_sources: int) -> str:
    """Drop citation markers that do not map to a listed source."""
    cleaned = _CITATION.sub(
        lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_sources else "", text
    )
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _has_citation(text: str) -> bool:
    return bool(_CITATION.search(text))


def synthesize(state: ContentState) -> dict:
    sources = state.get("sources", [])
    topic = state.get("topic") or state.get("request", "")
    if not sources:
        return {"findings": Findings(summary=NO_SOURCES_SUMMARY, key_findings=[])}

    numbered = "\n\n".join(
        f"[{i}] {s['title']}\nURL: {s['url']}\n{s['snippet']}" for i, s in enumerate(sources, 1)
    )
    structured = llm.get_llm().with_structured_output(Synthesis)
    result: Synthesis = structured.invoke(SYNTHESIS_PROMPT.format(topic=topic, sources=numbered))

    n = len(sources)
    summary = _clean_citations(result.summary, n)
    if not _has_citation(summary):  # an uncited summary is unsupported by search
        summary = UNCITED_SUMMARY
    # A finding that cites nothing valid is unsupported by search: drop it.
    key_findings = [
        f for f in (_clean_citations(k, n) for k in result.key_findings) if _has_citation(f)
    ]
    return {"findings": Findings(summary=summary, key_findings=key_findings)}
