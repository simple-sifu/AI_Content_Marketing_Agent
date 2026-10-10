---
title: 'Content Strategist report'
type: 'feature'
ticket: '3'
created: '2026-10-10'
status: 'built'
baseline_revision: '3ae7b8bc40bf4a04cd2a3da4d5e4e147df999be2'
route: 'full'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Research runs end with entry 2's interim plain-text dump of findings and sources, not a readable report.

**Approach:** Add a Content Strategist node after `synthesize` that turns `findings` and `sources` into a markdown research report (title, executive summary, key findings, sources, notes). It is the output for research requests and, until entries 4–5 land, for blog and LinkedIn requests too.

## Boundaries & Constraints

**Always:**
- Report sections in order: `# <title>`, `## Executive Summary`, `## Key Findings`, `## Sources`, `## Notes` (Notes only when there is something to say).
- `## Sources` is built in code from `state["sources"]` as `n. [title](url)`, numbered from 1 in state order, so `[n]` maps to `sources[n-1]`.
- Every `[n]` above `## Sources` maps to a listed source; any LLM-written text is citation-cleaned in code with entry 2's `_clean_citations`.
- No sources (missing key, all searches failed, or no results): a short report saying no sources were found, with the search problems in Notes; no Key Findings or Sources sections; no LLM call.
- Notes lists this run's `errors` and, for blog or LinkedIn intents, one line saying that format's writer is not built yet so this is the research report.
- Entry 1's LLM error convention for any LLM call this node makes.
- `synthesize` stops writing `final_output`; the strategist owns the research ending. Remove entry 2's interim `_render`.
- Tests are offline: fake LLM, mocked SerpAPI.
- Decision (user, 2026-10-10): the strategist makes one LLM call that writes the report title, a fuller cited executive summary, and a short "What this means" paragraph for Notes. Key Findings and Sources stay exactly as entry 2 produced them. If the LLM summary has no valid citation after cleaning, use entry 2's `findings.summary`; a blank title falls back to "Research Report: <topic>". No LLM call when there are no sources.

**Never:**
- No post-research router, blog or LinkedIn writer, or image work (entries 4–6).
- No change to query generation, search, or synthesis behavior beyond dropping the interim ending.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Research report | intent research, sources and cited findings | all five sections (Notes only if errors), every `[n]` maps to a listed source | — |
| Blog or LinkedIn request | intent blog/linkedin, research succeeded | same report, Notes says that writer is not built yet | — |
| Search problems | 1 of 3 searches failed | report as usual; Notes lists the failure | — |
| No sources | missing SerpAPI key, or no results | title, executive summary saying no sources were found, Notes with the reason; no Key Findings or Sources; no LLM call | — |
| Synthesis failed | `synthesize` set `intent=error` | strategist does not run; entry 2's error message stands | ends at `synthesize` |
| Strategist LLM fails | the strategist's LLM call raises an OpenAI or parse error | `intent=error`, readable message, run ends, no crash | entry 1 convention |

</frozen-after-approval>

## Code Map

- `content_agent/strategist.py` (new) -- `content_strategist(state)`. Reference for section layout and the deferred-format note: `git show 155fcac:content_agent/strategist.py`. Reuse `research._clean_citations`, `research.MISSING_SERPAPI_KEY`, `research.NO_SOURCES_SUMMARY`; if using an LLM, use `research._LLM_ERRORS`, `research._llm_failure`, and call `llm.get_llm` through the module.
- `content_agent/research.py` -- delete `_render`, `NO_FINDINGS_LINE` if unused, and `synthesize`'s `final_output` writes (both the no-sources and success returns). Leave everything else.
- `content_agent/graph.py` -- add `content_strategist`; replace `add_edge("synthesize", END)` with `add_conditional_edges("synthesize", _end_on_error("content_strategist"), ["content_strategist", END])`; strategist → END. Update the docstring diagram.
- `tests/test_research.py` -- assertions on entry 2's interim ending (`### Search problems`, `title — url` lines, `final_output` contents) move to the report's equivalents or to `findings`/`sources`/`errors`; keep every entry 2 matrix row covered.
- `tests/test_strategist.py` (new) -- one test per matrix row through `graph.invoke`, reusing `tests/conftest.py` fakes and the `serp` fixture pattern from `tests/test_research.py`.

## Tasks & Acceptance

**Execution:**
- [x] `content_agent/strategist.py` -- report node -- R7.
- [x] `content_agent/research.py`, `content_agent/graph.py` -- hand the ending to the strategist -- wiring.
- [x] `tests/test_research.py`, `tests/test_strategist.py` -- update interim-ending assertions and add matrix tests -- offline proof.

**Acceptance Criteria:**
- Given no API keys and no network, when `uv run pytest` runs, then all tests pass.
- Given real keys, when a research request runs under `langgraph dev`, then `final_output` is the markdown report and every `[n]` in it maps to a numbered source.

## Implementation Notes

- One structured LLM call (`Report`: title, executive_summary, what_this_means). The title is single-lined, stripped of `#` and all `[n]` markers; the summary and "What this means" go through `_clean_citations`. "What this means" is kept even without a citation; it appears in Notes as `**What this means:** ...`, followed by bullet lines for the deferred-writer note and this run's `errors`. So with the LLM, Notes appears whenever that paragraph is non-blank, not only when there are errors (per the 2026-10-10 decision).
- `NO_FINDINGS_LINE` is kept in `research.py`: the strategist uses it under Key Findings when sources exist but no finding survived cleaning.
- No sources and no `errors` (every search came back empty): Notes says "The searches ran but returned no results." (`NO_RESULTS_NOTE`).
- `tests/test_strategist.py` reuses `serp` and the fakes from `tests/test_research.py` by import.

## Plan Change Log

## Review Triage Log

**Pass 1 (quick lens)** — high 0 / medium 0 / low 6 / false 1 / maybe-false 0

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Fallback title uses the raw topic, so `[n]` in a topic reaches the `#` heading | low | patch | Verified: `_default_title` skips cleaning; reviewer's probe printed `# Research Report: Top 10 tools [2025] [3]`. Grouped with #2 (unsanitized text rendered into the report). Patch: swap brackets for parens. |
| 2 | Error lines in Notes can carry `[n]` from LLM-written queries | low | patch | Verified: `_search_error` embeds the query; Notes copies errors verbatim. Same patch as #1. |
| 3 | Uncited summary fallback can say "see cited findings below" above the no-findings line | low | reject | Needs both LLM calls uncited and every finding dropped; the fix adds a new branch. |
| 4 | `or NO_SOURCES_SUMMARY` fallback in the has-sources branch is the wrong message | low | reject | Unreachable in the graph: `synthesize` always writes a non-empty summary before the strategist runs. |
| 5 | `NO_FINDINGS_LINE` placeholder untested | low | patch | Verified: no test references it. Add a test. |
| 6 | `[99]`/`[7]` not-in-`final_output` checks are vacuous | low | patch | Verified: strategist's fake summary replaces the synthesis summary. Add a fallback-path test. |
| 7 | Notes appears without errors despite matrix "Notes only if errors" | false | reject | The user's 2026-10-10 decision in the frozen block places "What this means" in Notes, which supersedes that matrix note; behaviour follows the decision. |

## Verification

**Commands:**
- `env -u OPENAI_API_KEY -u SERPAPI_API_KEY uv run pytest -q` -- expected: all pass offline.

**Manual checks (if no CLI):**
- `uv run langgraph dev`, send "Give me an overview of AI in B2B marketing": a markdown report with the five sections comes back.
