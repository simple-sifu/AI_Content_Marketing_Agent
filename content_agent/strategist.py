"""Content Strategist: turns Deep Research findings and sources into a markdown report."""

from __future__ import annotations

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, Field

from content_agent import llm
from content_agent.research import (
    _LLM_ERRORS,
    NO_FINDINGS_LINE,
    NO_SOURCES_SUMMARY,
    _clean_citations,
    _has_citation,
    _llm_failure,
    _topic,
)
from content_agent.state import ContentState

NODE_NAME = "content_strategist"
NO_RESULTS_NOTE = "The searches ran but returned no results."

REPORT_PROMPT = """You are a content strategist. Using ONLY the research below, write:
- title: a short, specific report title (plain text, no markdown, no citations).
- executive_summary: 3-5 sentences summarizing the research for a marketing audience.
  Every factual claim must end with one or more citations like [1] or [2][3],
  referring to the source numbers below. Never cite a number that is not listed.
- what_this_means: one short paragraph (2-3 sentences) on what this means for a
  marketing team. Cite sources the same way if you state facts.

Topic: {topic}

Research summary:
{summary}

Key findings:
{key_findings}

Sources:
{sources}
"""


class Report(BaseModel):
    title: str = Field(description="Short report title, plain text.")
    executive_summary: str = Field(description="Cited executive summary, 3-5 sentences.")
    what_this_means: str = Field(description="Short paragraph on implications for marketers.")


def _unbracket(text: str) -> str:
    # Brackets would read as citation markers like [2025]; same treatment as source titles.
    return text.replace("[", "(").replace("]", ")")


def _default_title(topic: str) -> str:
    return f"Research Report: {_unbracket(topic)}"


def _clean_title(title: str) -> str:
    # One line, no heading markers, no citation markers (a title cites nothing).
    return _clean_citations(" ".join((title or "").split()).lstrip("#").strip(), 0)


def _notes(state: ContentState, extra: list[str]) -> list[str]:
    """Notes body: optional paragraphs (`extra`), then this run's errors."""
    parts = [p for p in extra if p]
    bullets = [_unbracket(e) for e in state.get("errors") or []]
    if bullets:
        parts.append("\n".join(f"- {b}" for b in bullets))
    return parts


def _assemble(
    title: str,
    summary: str,
    key_findings: list[str] | None,
    sources: list,
    notes: list[str],
) -> str:
    sections = [f"# {title}", "## Executive Summary\n\n" + summary]
    if sources:
        bullets = key_findings or [NO_FINDINGS_LINE]
        sections.append("## Key Findings\n\n" + "\n".join(f"- {k}" for k in bullets))
        # Built in code so [n] always maps to sources[n-1].
        sections.append(
            "## Sources\n\n"
            + "\n".join(f"{i}. [{s['title']}]({s['url']})" for i, s in enumerate(sources, 1))
        )
    if notes:
        sections.append("## Notes\n\n" + "\n\n".join(notes))
    return "\n\n".join(sections) + "\n"


def content_strategist(state: ContentState) -> dict:
    topic = _topic(state)
    sources = list(state.get("sources") or [])
    findings = state.get("findings") or {}

    if not sources:  # nothing to report on: no LLM call
        # Errors explain why; with none, every search simply came back empty.
        notes = _notes(state, [] if state.get("errors") else [NO_RESULTS_NOTE])
        report = _assemble(_default_title(topic), NO_SOURCES_SUMMARY, None, [], notes)
        return {"final_output": report}

    n = len(sources)
    key_findings = list(findings.get("key_findings") or [])
    numbered = "\n".join(f"[{i}] {s['title']} ({s['url']})" for i, s in enumerate(sources, 1))
    prompt = REPORT_PROMPT.format(
        topic=topic,
        summary=findings.get("summary") or "",
        key_findings="\n".join(f"- {k}" for k in key_findings) or "(none)",
        sources=numbered,
    )
    try:
        structured = llm.get_llm().with_structured_output(Report)
        result = structured.invoke(prompt)
        if not isinstance(result, Report):
            raise OutputParserException("structured output did not match Report")
    except _LLM_ERRORS as exc:
        return _llm_failure(state, NODE_NAME, exc)

    title = _clean_title(result.title) or _default_title(topic)
    summary = _clean_citations(result.executive_summary or "", n)
    if not _has_citation(summary):  # an uncited summary is unsupported by search
        summary = findings.get("summary") or NO_SOURCES_SUMMARY
    meaning = _clean_citations(result.what_this_means or "", n)
    notes = _notes(state, [f"**What this means:** {meaning}" if meaning else ""])
    return {"final_output": _assemble(title, summary, key_findings, sources, notes)}
