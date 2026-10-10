---
title: 'Refactor sweep'
type: 'refactor'
ticket: '8'
created: '2026-10-10'
status: 'built'
baseline_revision: 'd07940ae7482aeb1e2361989cf95890a97bb8326'
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

**Problem:** Two findings put off during the epic are still open. Research queries carry stale years and off-topic search results reach the synthesis (story 2's live run). A reused `langgraph dev` thread can show an earlier run's `target_format` (story 4's review). `deferred-work.md` also still lists items that later stories finished.

**Approach:** Give the query prompt today's date, drop search results that don't mention the topic, and clear `target_format` at the start of every run alongside the image fields. Then record which deferred entries are closed and by what.

## Boundaries & Constraints

**Always:**
- Query date: `QUERY_PROMPT` states today's date (ISO, from a small `_today()` helper so tests can pin it). It tells the model to use the current year for time-sensitive queries and never a past year unless the topic names one.
- Relevance filter, in `run_searches` before dedupe:
  - Topic keywords are the topic's lowercase word tokens minus a short stopword list (`a an and the of in on for to with about how what vs`). Tokens keep internal punctuation, so `b2b` and `node.js` survive.
  - A result is kept when at least `ceil(k/2)` of the `k` keywords appear as whole words in its title and snippet (case-insensitive). With no keywords, every result is kept.
  - Dropped results never become sources, so citation numbering stays contiguous. If every result is dropped, the run takes the existing no-sources path.
  - The filter adds nothing to `errors`: an off-topic result isn't a failure.
- Thread reuse: `query_handler`'s reset (today `_IMAGE_RESET`) also clears `target_format` to `""`, on all three returns.
- `deferred-work.md`: append one "Closed by story 8 sweep" block that lists each existing entry with its status and the story or commit that closed it. Existing entries are not edited.
- The offline suite passes. Each change gets tests: the date is in the prompt; on-topic results are kept and off-topic ones dropped (including the story 2 examples "Case IH" and "case.edu" for "AI in B2B marketing"); all-dropped goes to no-sources; `target_format` is cleared on a reused thread.

**Never:**
- No change to the writers, validators, image generator, router decisions or README behaviour descriptions. No LLM-based relevance filter, which would add a call and cost per request. No sharing of the blog and LinkedIn revise loops.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Query prompt | any research run | prompt contains `Today's date is <YYYY-MM-DD>` | — |
| Mixed results | topic "AI in B2B marketing"; results "AI tools for B2B marketing teams", "Case IH tractors", "case.edu admissions" | only the first becomes a source, as `[1]` | — |
| One-word topic | topic "kubernetes"; one result mentions it, one doesn't | one source | — |
| All off-topic | every result fails the filter | `sources=[]`; strategist no-sources report; `errors` unchanged | — |
| Reused thread | blog run (`target_format=blog`), then an image run on the same thread | second result has `target_format == ""` | — |

</frozen-after-approval>

## Code Map

- `content_agent/research.py` -- `QUERY_PROMPT` and `generate_queries` (add `today=_today()`); `run_searches` (lines ~135–165) builds `Source`s from SerpAPI results: apply `_on_topic(result, keywords)` there, before the URL dedupe. `_topic` gives the topic. Leave `serpapi_search`, `_search_error` and `synthesize` unchanged.
- `content_agent/router.py` -- `_IMAGE_RESET`: rename it to `_RUN_RESET`, add `"target_format": ""`, and update its comment.
- `tests/test_research.py` -- the `_results(prefix)` fixtures produce titles like "a title 1" that won't contain the topic. Make the fixture titles or snippets mention the topic (e.g. snippet `f"{prefix} snippet {i} about AI in B2B marketing"`) so existing tests keep their sources. Add the filter and date tests here.
- `tests/test_blog.py`, `tests/test_linkedin.py` -- the no-sources tests assert `"target_format" not in result`; change them to `== ""`.
- `tests/test_query_handler.py` or `tests/test_images.py` -- add the reused-thread `target_format` test next to the existing image-field one.
- `_bmad-output/initiative-content-marketing-agent/deferred-work.md` -- append the closure block. The entries are: blog writer (story 4), LinkedIn writer (story 5), image generator (story 6), OpenAI errors (story 1's convention), research query quality (this story).

## Tasks & Acceptance

**Execution:**
- [x] `content_agent/research.py` -- dated query prompt and relevance filter.
- [x] `content_agent/router.py` -- clear `target_format` per run.
- [x] `tests/test_research.py`, `tests/test_blog.py`, `tests/test_linkedin.py`, `tests/test_images.py` -- fixtures updated and every matrix row tested.
- [x] `_bmad-output/initiative-content-marketing-agent/deferred-work.md` -- closure block.

**Acceptance Criteria:**
- Given no API keys and no network, when `uv run pytest` runs, then all tests pass.
- Given real keys, when "Give me an overview of AI in B2B marketing" runs, then the generated queries use no year before the current one, and every source's title or snippet mentions the topic's keywords (recorded in Implementation Notes).

## Implementation Notes

- `topic_keywords` is public (tests import it). `_on_topic` matches the title and snippet only, not the URL. The fixture `_results` snippets now name the topic, and `test_bracketed_title_is_not_a_citation` gained an on-topic snippet.
- The `target_format` reused-thread test lives in `tests/test_images.py` next to the image-field one, since the second run is an image request.
- The closure block in `deferred-work.md` also closes story 4's rejected review row 1.
- Live (2026-10-10, "Give me an overview of AI in B2B marketing"): the queries were "AI in B2B marketing overview 2026", "latest trends and statistics AI B2B marketing 2026" and "case studies of AI applications in B2B marketing 2026", with no earlier year. All 9 sources pass `_on_topic` (B2B marketing trend and AI articles from Forrester, HubSpot, Cognism and others), with `errors=[]`.

## Plan Change Log

## Review Triage Log

**Pass 1 (quick lens)**: high 0 / medium 0 / low 4 / false 1 / maybe-false 0; plus 1 bookkeeping note

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Mixed-results test doesn't prove the kept result is cited `[1]` | low | patch | Verified. The test now asserts the Sources line and that every marker is `[1]`. |
| 2 | Possessive/hyphenated topic words (`ai's`, `ai-powered`) never match | low | patch | Verified with the reviewer's examples (topics are LLM-extracted, so realistic). A possessive `'s` is stripped; a hyphenated keyword matches with a hyphen or a space. Tested. |
| 3 | Request-text fallback topic gives many keywords and a higher bar | low | reject | Only reached when the LLM returns a blank topic. Unlikely in everyday use, and a fix needs extra stopword logic. |
| 4 | `[:RESULTS_PER_QUERY]` cut before the filter wastes slots | false | reject | `serpapi_search` requests `num=RESULTS_PER_QUERY`, so there are no extra results to fill the slots; the order doesn't change the outcome. |
| 5 | Closure block says "every entry above" but adds a story 4 review row | low | patch | Wording fixed. |
| 6 | Execution checkboxes unticked, logs empty | — | resolved | Ticked when marked built; this log is filled. |

## Verification

**Commands:**
- `env -u OPENAI_API_KEY -u SERPAPI_API_KEY uv run pytest -q` -- expected: all pass.

**Manual checks (if no CLI):**
- One live research run: inspect `queries` and `sources` as in the second acceptance criterion.
