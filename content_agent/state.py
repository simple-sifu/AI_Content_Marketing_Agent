"""Shared graph state: the contract every agent node reads from and writes to."""

from __future__ import annotations

from typing import TypedDict


class Source(TypedDict):
    title: str
    url: str
    snippet: str


class Findings(TypedDict):
    # Cited executive summary; every [n] maps to sources[n-1].
    summary: str
    # Cited key findings; uncited findings are dropped before they reach state.
    key_findings: list[str]


class ContentState(TypedDict, total=False):
    # Raw user request.
    request: str
    # Query Handler classification: research | blog | linkedin | image,
    # or the non-classification values "empty" (no request) and "error" (an LLM failed;
    # also set by research nodes, which end the run).
    intent: str
    # Topic extracted by the Query Handler ("" when empty or on error).
    topic: str
    # Deep Research: the 3 search queries that ran this run.
    queries: list[str]
    # Deep Research: deduped sources; position i is citation [i+1].
    sources: list[Source]
    # Deep Research: cited synthesis of `sources` (handoff to report/blog/LinkedIn writers).
    findings: Findings
    # Post-research router decision: "blog" | "linkedin" | "report" ("" when the router failed).
    # Only written when research found sources; otherwise the strategist reports directly.
    target_format: str
    # Final user-facing markdown.
    final_output: str
    # Problems from the current run only. Deliberately has no reducer (no operator.add):
    # the Query Handler overwrites it at the start of every run, so a reused
    # `langgraph dev` thread never carries stale errors. Later nodes accumulate within
    # the run by returning state["errors"] + their new entries.
    errors: list[str]
