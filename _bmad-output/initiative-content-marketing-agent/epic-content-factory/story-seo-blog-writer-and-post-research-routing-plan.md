---
title: 'SEO Blog Writer and post-research routing'
type: 'feature'
ticket: '4'
created: '2026-10-10'
status: 'built'
baseline_revision: '2c1cba6bcdab1ccea434b5a7733873d0c3696dbc'
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

**Problem:** Blog requests get the research report, not a blog post, and nothing decides after research which format to write.

**Approach:** Add an LLM post-research router that picks `blog` or `report`, and an SEO Blog Writer that turns entry 2's cited findings into a long-form markdown post. A shared validator checks the post's SEO rules; the writer revises against it before returning.

## Boundaries & Constraints

**Always:**
- Router: one LLM call returning `target_format` of `blog` or `report` from the request and intent; written to state every time it runs. It runs only when `sources` is non-empty; with no sources the run goes straight to the strategist's no-sources report (no blog is written without sources).
- Post shape, assembled in code: YAML front matter with `meta_description` (120–160 characters), one `# <title>` H1, body with at least two `##` and at least one `###`, then `## Sources` built from `state["sources"]` as `n. [title](url)`. Any `#` heading the LLM puts in the body is demoted to `##`.
- Long-form: body (excluding front matter and Sources) at least 800 words; prompt targets 1,200–1,600.
- Primary keyword is entry 1's `topic`. Density = case-insensitive whole-phrase matches × words in the phrase ÷ body words × 100, and must be 1–2% inclusive.
- Every `[n]` in the post maps to a listed source; cleaned in code with `_clean_citations`; brackets in the title and meta description become parentheses.
- `content_agent/validators.py` holds `validate_blog(post, sources, keyword) -> list[str]` (empty list = valid). The writer, the tests, and the live check all use it.
- Revision loop: if the draft fails validation, the writer sends the failures back to the LLM for up to 2 revisions; if it still fails, it returns the last draft and appends each failed check to `errors` (the post is still the output).
- Entry 1's LLM error convention in the router and the writer.
- Tests are offline: fake LLM, mocked SerpAPI.

**Never:**
- No LinkedIn writer or `linkedin` router option (entry 5); no image work (entry 6).
- No change to query generation, search, or synthesis.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Blog request | intent blog, sources present, router picks blog | `final_output` is a post that passes `validate_blog`; `target_format=blog` | — |
| Research request | intent research, router picks report | strategist report, unchanged from entry 3 | — |
| LinkedIn request | intent linkedin, router picks report | strategist report with entry 3's "LinkedIn writer is not built yet" note | — |
| Blog with no sources | intent blog, `sources=[]` | router not called; strategist no-sources report | — |
| Density off, fixed on revision | first draft 3%, revision 1.5% | revised post returned, `errors` unchanged | — |
| Still invalid after 2 revisions | every draft fails a check | last draft returned; one `errors` entry per failed check | — |
| Bad citations / stray H1 | LLM cites `[99]`, adds `# Heading` in body | marker removed, heading demoted; validator passes | — |
| Router or writer LLM fails | OpenAI or parse error | `intent=error`, readable message, run ends | entry 1 convention |

</frozen-after-approval>

## Code Map

- `content_agent/validators.py` (new) -- `validate_blog`, plus small helpers (`keyword_density`, `body_words`) the tests import. Reuse `research._CITATION` for marker checks.
- `content_agent/blog.py` (new) -- `blog_writer(state)`. Structured LLM output `BlogDraft(title, meta_description, body)`; code assembles front matter, H1, demoted body, Sources. Revision prompt includes the validator's failure list. Reuse `research._LLM_ERRORS`, `_llm_failure`, `_clean_citations`, `_topic`; `strategist._unbracket` for title/meta. Call `llm.get_llm` through the module.
- `content_agent/router.py` -- add `PostResearchDecision(target_format: Literal["blog","report"])`, `post_research_router(state)` (LLM, entry 1 convention), and `route_after_research(state)` → `blog_writer` | `content_strategist` | END on `intent=error`. Leave `query_handler` and `route_after_query_handler` unchanged.
- `content_agent/state.py` -- add `target_format: str`.
- `content_agent/graph.py` -- `synthesize --(ok, sources)--> post_research_router --> blog_writer | content_strategist`; `synthesize --(ok, no sources)--> content_strategist`; END on `intent=error` after `synthesize`, router, and writer. Update docstring diagram.
- `content_agent/strategist.py` -- `_DEFERRED_WRITERS` drops `blog` (the blog writer exists now); keep `linkedin`.
- `tests/test_research.py`, `tests/test_strategist.py` -- the fake LLM must also answer `PostResearchDecision` (default `report`) so existing paths still reach the strategist; drop or update assertions on the blog "not built yet" note.
- `tests/test_validators.py`, `tests/test_blog.py` (new) -- validator unit tests (each rule pass/fail, density math) and one graph test per matrix row; fake `BlogDraft` fixtures built to pass and to fail specific rules.

## Tasks & Acceptance

**Execution:**
- [x] `content_agent/validators.py` -- SEO validator -- one definition of "valid" for code, tests, and live check.
- [x] `content_agent/state.py`, `content_agent/router.py` -- `target_format` and post-research router -- R2.
- [x] `content_agent/blog.py` -- writer with assembly and revision loop -- R4.
- [x] `content_agent/graph.py`, `content_agent/strategist.py` -- wiring and note update.
- [x] `tests/conftest.py` (if needed), `tests/test_research.py`, `tests/test_strategist.py`, `tests/test_validators.py`, `tests/test_blog.py` -- offline proof.

**Acceptance Criteria:**
- Given no API keys and no network, when `uv run pytest` runs, then all tests pass.
- Given real keys, when "Write a blog post about remote work tools" runs under `langgraph dev`, then `validate_blog(final_output, sources, topic)` returns `[]`.

## Implementation Notes

- `FakeLLM` (tests/conftest.py) accepts a list per schema: one item per call, last repeats; an exception item is raised. Used for revision-loop tests.
- Body/draft fixture builders live in `tests/test_validators.py` and are imported by `tests/test_blog.py` (same pattern as test_strategist importing from test_research).
- Title cleaning reuses `strategist._clean_title` (drops `[n]` markers) then `_unbracket`, so `[2]` disappears and `[Updated]` becomes `(Updated)`.
- The writer drops an LLM-written Sources/References section and a leading H1 that repeats the title.
- Live tuning (gpt-4o-mini): the first draft tends to be short and overuse the keyword, and plain "fix these failures" revisions were often returned unchanged. The revision prompt now puts the brief first and the failures last, gives a computed mention target for the draft's current length with the lines/sections to change, and revisions run at temperature 0.2. Density failure messages state the allowed mention range. Result: 7 of the last 8 live runs of "Write a blog post about remote work tools" returned a post with `validate_blog == []`; the failure kept the last draft and listed the check in `errors`, as designed.

## Plan Change Log

## Review Triage Log

**Pass 1 (quick lens)** — high 0 / medium 2 / low 5 / false 0 / maybe-false 0

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | `target_format` survives on a reused thread when the router is skipped | low | reject | Reproduced, but routing never reads it on those paths and output is correct; clearing it means touching query generation, which the plan excludes, for a state-only cosmetic. |
| 2 | Topics with punctuation (`Node.js`, `vs.`, `C++`) never match, so density is always 0% | medium | patch | Verified by the reviewer's probe; the topic is LLM-extracted so such topics are realistic. Patch: escape tokens, flexible whitespace/hyphen joins, word lookarounds. |
| 3 | Mention budget computed for 1,000 words vs a 1,200–1,600-word brief | medium | patch | Verified: 4 mentions × 3 words at 1,400 words = 0.86%. Grouped with #4 (live AC failed 1 in 8). Patch: budget for 1,400 words. |
| 4 | Live AC 2 not consistently met (7/8) | medium | patch | Same root cause as #3. |
| 5 | Mid-body References/Citations heading truncates the rest of the post | low | patch | Verified: `_clean_body` breaks on first match at any level. Patch: drop only a trailing section. |
| 6 | Density failure message can show an impossible range ("1-0") | low | patch | Verified: unclamped in validator, clamped in blog. Direct clamp. |
| 7 | Our own `ValueError`s reported as LLM failures | low | patch | Verified: try covers `_assemble`/`validate_blog`; other nodes keep only the invoke inside. Narrow the try. |

## Design Notes

The density formula counts the whole phrase, so a 4-word topic needs far fewer mentions than a 1-word one: a 1,400-word post with topic "remote work tools" (3 words) needs 5–9 mentions. Validate on body text only so the Sources list and front matter don't skew the count.

## Verification

**Commands:**
- `env -u OPENAI_API_KEY -u SERPAPI_API_KEY uv run pytest -q` -- expected: all pass offline.

**Manual checks (if no CLI):**
- With real keys, run a blog request through `langgraph dev`, then `uv run python -c` with `validate_blog` on the returned post: expect `[]`.
