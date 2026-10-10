---
title: 'Core LangGraph content agent: router, deep research, content strategist'
type: 'feature'
ticket: ''
created: '2026-10-10'
status: 'ready-for-dev'
baseline_revision: ''
route: 'full'
route_source: 'auto'
risk: 'low'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Solo creators and small teams spend hours researching each content piece. The content factory needs a working core — routing, cited research, and a readable report — that the later blog, LinkedIn, and image agents plug into.

**Approach:** A LangGraph `StateGraph` runnable with `langgraph dev`: an LLM Query Handler classifies the request, a Deep Research agent generates several search queries, runs them through SerpAPI, and synthesizes findings with numbered citations, then a post-research router sends the result to the Content Strategist, which formats a markdown research report.

## Boundaries & Constraints

**Always:** Read `OPENAI_API_KEY`, `SERPAPI_API_KEY`, `OPENAI_MODEL` from the environment (`.env` via `langgraph.json`/python-dotenv). Router decisions use structured output (Pydantic), not string parsing. Every claim in the report that comes from search carries a `[n]` citation that maps to a listed source URL. Tests never hit the network.

**Never:** Implement the SEO Blog Writer, LinkedIn Writer, or Image Generator (deferred in `deferred-work.md`). No UI, no database, no LangGraph Cloud deploy. Never log or print API keys.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Research request | "Research AI trends in B2B marketing" | intent `research`; 3 queries run; report with summary, key findings, `[n]` citations, Sources list | No error expected |
| Some searches fail | 1 of 3 SerpAPI calls raises / quota exceeded | Report built from successful results; failure noted in state `errors` | Catch per-query, continue |
| No results at all | All searches fail or return nothing | Report says no sources were found; no fabricated citations | Graph completes, no exception |
| Missing SerpAPI key | `SERPAPI_API_KEY` empty | Clear error message in final output naming the missing variable | No crash at import time |
| Empty request | "" or whitespace | Final output asks the user for a topic | Short-circuit before research |

## Decisions

- **Model:** read `OPENAI_MODEL`, default `gpt-4o-mini`.
- **Deferred formats:** blog / LinkedIn / image requests run research and return the report with a one-line note that the requested format is coming.
- **Search budget:** exactly 3 SerpAPI queries per request.
- **Version control:** `git init` with `.gitignore` excluding `.env`; commit the pre-implementation state as `baseline_revision`. Never push.

</frozen-after-approval>

## Code Map

Greenfield: the project holds only `.env`, `skills-lock.json`, `.claude/`, `_bmad/`, `_bmad-output/`. No existing code to reuse.

- `.env` -- already has `OPENAI_API_KEY`, `SERPAPI_API_KEY` (both set), `OPENAI_MODEL=gpt-4o-mini`; also unrelated Alpha Vantage vars from another project — leave the file untouched.
- Toolchain: `uv` 0.12.3, system Python 3.14.6. Pin the project to Python 3.12 (`.python-version`) for dependency wheel availability.

## Tasks & Acceptance

**Execution:**
- [ ] `pyproject.toml`, `.python-version`, `.gitignore` -- uv project; deps `langgraph`, `langchain-openai`, `langchain-core`, `google-search-results`, `python-dotenv`, `pydantic`; dev `pytest`, `langgraph-cli[inmem]`; ignore `.env`, `.venv`, `__pycache__`, `_bmad/render` -- reproducible env
- [ ] `langgraph.json` -- graph `content_agent` → `./content_agent/graph.py:graph`, `env: .env`, deps `["."]` -- `langgraph dev` + Cloud-ready
- [ ] `content_agent/state.py` -- `ContentState` TypedDict: `request`, `intent`, `topic`, `queries`, `sources` (list of {title,url,snippet}), `findings`, `target_format`, `final_output`, `errors` -- shared contract for later agents
- [ ] `content_agent/llm.py` -- `get_llm()` returning `ChatOpenAI(model=OPENAI_MODEL, temperature=…)` -- single model switch point
- [ ] `content_agent/router.py` -- `query_handler` (structured `RouteDecision{intent: research|blog|linkedin|image, topic}`) and `post_research_router` (picks `target_format`; only `report` is wired now) -- both routing passes from the brief
- [ ] `content_agent/research.py` -- `generate_queries`, `run_searches` (SerpAPI organic results, per-query try/except, dedupe by URL), `synthesize` (findings with `[n]` citations) -- Deep Research agent
- [ ] `content_agent/strategist.py` -- `content_strategist` formats markdown: title, executive summary, key findings, sources -- Content Strategist agent
- [ ] `content_agent/graph.py` -- build and compile `graph` with conditional edges -- entry point
- [ ] `tests/test_graph.py` -- fake LLM + mocked SerpAPI covering every I/O matrix row -- offline verification

**Acceptance Criteria:**
- Given the venv is synced, when `uv run langgraph dev` starts, then the `content_agent` graph loads in LangGraph Studio without errors.
- Given valid keys, when the graph is invoked with a research request, then `final_output` is a markdown report whose every `[n]` maps to a URL in its Sources section.
- Given the repository, when `uv run pytest` runs offline, then all tests pass.

## Implementation Notes

## Plan Change Log

## Review Triage Log

## Design Notes

Graph shape (later agents add nodes at the two routers' branches):

```
START → query_handler ─┬─ empty → END (ask for topic)
                       └─ research → generate_queries → run_searches → synthesize
                          → post_research_router → content_strategist → END
```

## Verification

**Commands:**
- `uv run pytest -q` -- expected: all pass, no network
- `uv run python -c "from content_agent.graph import graph; print(graph.get_graph().draw_ascii())"` -- expected: prints graph

**Manual checks (if no CLI):**
- `uv run langgraph dev`, invoke with a research request in Studio; report has citations and sources.

