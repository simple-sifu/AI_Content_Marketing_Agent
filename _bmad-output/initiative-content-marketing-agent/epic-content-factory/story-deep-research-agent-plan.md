---
title: 'Deep Research agent'
type: 'feature'
ticket: '2'
created: '2026-10-10'
status: 'built'
baseline_revision: '42d8c8aadec14f4cf29019d93d691b3fc6213b22'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Research, blog, and LinkedIn requests stop at classification, so nothing the factory writes can rest on real sources.

**Approach:** Route those three intents into a Deep Research agent: an LLM writes 3 search queries, SerpAPI runs them, sources are deduped and numbered, and an LLM synthesizes cited findings into `findings` and `sources` (the handoff entries 3–5 consume). Until entry 3 exists, those runs end with the cited findings and a numbered source list as plain text.

## Boundaries & Constraints

**Always:**
- Exactly 3 distinct queries per run; if the LLM returns fewer or duplicates, pad from the topic so 3 still run.
- Per-query isolation: one failed search adds an `errors` entry and the others still run.
- The SerpAPI key never appears in `final_output` or `errors`: never put raw exception text in either (class name only); SerpAPI's in-band error message may be included only after the key is redacted from it.
- Every `[n]` kept in the summary and in each finding maps to a listed source (enforced in code, not only in the prompt); uncited findings are dropped; an uncited summary is replaced by a fixed line.
- Entry 1's LLM error convention: an OpenAI or parse failure in a research node gives `intent=error`, a `llm_error()` message in `final_output`, a `"<node>: <Class>"` entry in `errors`, and the run ends there.
- `errors` stays reducer-free: research nodes return `state["errors"] + new`, so entries from this run accumulate while the Query Handler's reset still clears old runs.
- Every run that reaches research overwrites `queries`, `sources`, and `findings`.
- Tests are offline: fake LLM, mocked SerpAPI, no network.

**Never:**
- No report formatting, post-research router, writers, or images (entries 3–6).
- No change to image, empty, or classification-error behavior from entry 1.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Research happy path | intent research/blog/linkedin, 3 searches return results | 3 queries run; `sources` deduped by URL, numbered from 1; `findings` cited; `final_output` shows summary, findings, numbered sources; `errors=[]` | — |
| Partial failure | 1 of 3 searches raises or returns an in-band error | other 2 queries' sources used; one `errors` entry naming the failed query; findings still produced | isolated per query |
| All searches fail / no results | every search fails or returns nothing | `sources=[]`; findings is a fixed "no sources found" summary with no LLM synthesis call; `final_output` says so and lists the errors | — |
| Missing SerpAPI key | `SERPAPI_API_KEY` unset or blank | no searches attempted; `errors` has one readable entry telling the user to set `SERPAPI_API_KEY`; same ending as no sources | — |
| Key leak attempt | exception or in-band error whose text contains the key | key absent from `final_output` and every `errors` entry | redacted / class name only |
| Bad citations | LLM cites `[99]` or omits citations | invalid markers stripped; uncited findings dropped; uncited summary replaced | — |
| LLM fails | query generation or synthesis raises OpenAI/parse error | `intent=error`, readable message, run ends, no crash | entry 1 convention |
| Image intent | intent image | unchanged from entry 1: no research, classification message | — |

</frozen-after-approval>

## Code Map

- `content_agent/state.py` -- add `Source` (`title`, `url`, `snippet`), `Findings` (`summary`, `key_findings: list[str]`), and `ContentState.queries`, `.sources` (position i is citation `[i+1]`), `.findings`. Keep `errors` reducer-free and update its comment for in-run accumulation.
- `content_agent/research.py` (new) -- `generate_queries`, `run_searches`, `synthesize`, plus `serpapi_search(query, api_key)` as the single SerpAPI call site (tests patch it). Reference for structure, prompts, query padding, dedupe, and `_clean_citations`: `git show 155fcac:content_agent/research.py`. Differences from that reference: wrap LLM calls in entry 1's convention (catch `(openai.OpenAIError, ValueError, OpenAIRefusalError)` exactly as `content_agent/router.py` does, call `llm.get_llm` through the module); error text uses class name, not `str(exc)`; no LLM call when there are no sources; append to `state["errors"]` instead of replacing it.
- `content_agent/router.py` -- add `route_after_query_handler(state)`: `research|blog|linkedin` → research, anything else → END. Leave `query_handler` unchanged.
- `content_agent/graph.py` -- `START → query_handler → (research intents) generate_queries → run_searches → synthesize → END`; after `generate_queries` and `synthesize`, route to END when `intent == "error"`. Update the module docstring diagram.
- `content_agent/research.py` final step -- `synthesize` writes `final_output`: summary, a findings list, and a numbered `Sources` list (`n. title — url`), plus a short "Search problems" list when `errors` is non-empty. Entry 3 replaces this ending.
- `pyproject.toml` / `uv.lock` -- add `google-search-results` (import name `serpapi`, `GoogleSearch(params).get_dict()`); `uv sync`.
- `.env.example` -- add `SERPAPI_API_KEY=` under the OpenAI block.
- `tests/conftest.py` (new) -- move `FakeLLM`, `_Structured`, the `no_network` autouse guard, and `use_llm` out of `tests/test_query_handler.py` so both test files share them; extend `FakeLLM` to return per-schema responses and raise per-schema errors.
- `tests/test_query_handler.py` -- research/blog/linkedin cases now continue into research, so either assert classification on the `query_handler` node output directly or supply research fakes; keep every entry 1 matrix row covered, including the exact image ending.
- `tests/test_research.py` (new) -- one test per I/O matrix row through `graph.invoke`, patching `research.serpapi_search` and setting `SERPAPI_API_KEY`.

## Tasks & Acceptance

**Execution:**
- [ ] `pyproject.toml`, `uv.lock`, `.env.example` -- add SerpAPI dependency and key -- R3 needs search.
- [ ] `content_agent/state.py` -- research fields -- handoff contract for entries 3–5.
- [ ] `content_agent/research.py` -- the three nodes and `serpapi_search` -- R3.
- [ ] `content_agent/router.py`, `content_agent/graph.py` -- route research intents and end on error -- wiring.
- [ ] `tests/conftest.py`, `tests/test_query_handler.py`, `tests/test_research.py` -- shared fakes and matrix tests -- offline proof.

**Acceptance Criteria:**
- Given no `OPENAI_API_KEY` or `SERPAPI_API_KEY` and no network, when `uv run pytest` runs, then all entry 1 and entry 2 tests pass.
- Given real keys in `.env`, when a research request runs under `langgraph dev`, then the final state has 3 `queries`, non-empty `sources`, and cited `findings`, and every `[n]` in the output maps to a listed source.

## Implementation Notes

## Plan Change Log

## Review Triage Log

**Pass 1 (quick lens)** — high 0 / medium 1 / low 5 / false 1 / maybe-false 0

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | `serpapi_search` has no practical timeout | medium | patch | Verified: `SerpApiClient.__init__(timeout=60000)` → `requests.get(..., timeout=self.timeout)` (serp_api_client.py:35,59); a hung query blocks every later query. Patch: set a 30 s timeout on the instance. |
| 2 | Non-`[n]` bracket forms (`[2-99]`, `[ 99 ]`, `[1, 2]`) escape citation cleaning | low | reject | Real but the prompt mandates `[n]` and gpt-4o-mini follows it; the fix needs a broader citation grammar (new parsing branches), not a direct correction. |
| 3 | Source titles with brackets (e.g. `[2025]`) put unmapped `[n]` into `final_output` | low | patch | Verified: `_render` prints titles verbatim; bracketed years in titles are common. Patch: strip brackets from titles at ingest. |
| 4 | Removed marker leaves a space before punctuation | low | patch | Verified: `"Big claim [99]."` → `"Big claim ."`. Direct regex fix. |
| 5 | No `_end_on_error` after `synthesize` despite Code Map | false | reject | Both outcomes end the run today and there is no next node to route to; the comment hands the conditional to entry 3, where the node it would guard first exists. |
| 6 | Missing SerpAPI key detected only after the query LLM call | low | reject | Real but one cheap call, only while misconfigured; fix adds a new branch upstream. |
| 7 | Partial-failure test `or` assertion is weak | low | patch | Verified: does not prove raw exception text is excluded. Direct assertion fix. |

## Design Notes

Ending `intent=error` on a research-node LLM failure reuses entry 1's marker, so later routers need only one stop check. The original intent is lost for that run, which is acceptable: the run has ended and the next run re-classifies.

## Verification

**Commands:**
- `uv sync` -- expected: lockfile updated, no errors.
- `env -u OPENAI_API_KEY -u SERPAPI_API_KEY uv run pytest -q` -- expected: all pass offline.

**Manual checks (if no CLI):**
- With real keys, `uv run langgraph dev`, send "Give me an overview of AI in B2B marketing": cited findings and a numbered source list come back.
