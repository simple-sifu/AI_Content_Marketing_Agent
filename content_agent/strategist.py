"""Content Strategist: formats research into a markdown report."""

from __future__ import annotations

from content_agent.research import MISSING_SERPAPI_KEY, NO_SOURCES_SUMMARY
from content_agent.state import ContentState

DEFERRED_FORMATS = {
    "blog": "SEO blog post",
    "linkedin": "LinkedIn post",
    "image": "image generation",
}


def content_strategist(state: ContentState) -> dict:
    errors = state.get("errors", []) or []
    topic = state.get("topic") or state.get("request", "")

    if MISSING_SERPAPI_KEY in errors:
        return {"final_output": f"**Configuration error:** {MISSING_SERPAPI_KEY}"}

    findings = state.get("findings") or {}
    sources = state.get("sources", []) or []
    lines: list[str] = [f"# Research Report: {topic}", ""]

    deferred = DEFERRED_FORMATS.get(state.get("intent", ""))
    if deferred:
        lines += [
            f"> Note: {deferred} output is coming soon; here is the research report for now.",
            "",
        ]

    summary = findings.get("summary") or ("" if sources else NO_SOURCES_SUMMARY)
    if summary:
        lines += ["## Executive Summary", "", summary, ""]

    if sources:
        key_findings = findings.get("key_findings") or []
        if key_findings:
            lines += ["## Key Findings", ""]
            lines += [f"- {k}" for k in key_findings]
            lines.append("")
        lines += ["## Sources", ""]
        lines += [f"{i}. [{s['title']}]({s['url']}) - {s['url']}" for i, s in enumerate(sources, 1)]
        lines.append("")

    if errors:
        lines += ["## Notes", ""]
        lines += [f"- {e}" for e in errors]
        lines.append("")

    return {"final_output": "\n".join(lines).rstrip() + "\n"}
