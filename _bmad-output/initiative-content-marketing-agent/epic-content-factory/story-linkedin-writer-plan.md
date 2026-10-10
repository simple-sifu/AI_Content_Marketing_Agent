---
title: 'LinkedIn Writer'
type: 'feature'
ticket: '5'
created: '2026-10-10'
status: 'built'
baseline_revision: 'cfaad792ce6408662bf7797412864ce9907ee8ba'
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

**Problem:** LinkedIn requests get the research report with a "LinkedIn writer is not built yet" note, not a LinkedIn post.

**Approach:** Add `linkedin` to entry 4's post-research router and a LinkedIn Writer node that turns entry 2's findings into a plain-text post. The post has a hook, a story, a CTA and hashtags, with a short Sources list of research URLs after it. A shared validator checks the post, and the writer revises against it before returning, the same way the blog writer does.

## Boundaries & Constraints

**Always:**
- Router: `target_format` becomes `blog` | `linkedin` | `report`; the prompt maps LinkedIn-post requests to `linkedin`. It still runs only when `sources` is non-empty, so a LinkedIn request with no sources gets the strategist's no-sources report.
- Post shape, assembled in code from a structured draft (`hook`, `story`, `cta`, `hashtags`, `source_numbers`), as paragraphs separated by blank lines: hook (one paragraph, at most 210 characters, so it fits above LinkedIn's "see more" cut), story (1 or more paragraphs), CTA (one paragraph), then one hashtag line. Then a blank line, `Sources:`, and one `- <url>` per line.
- Length: 1300–1600 characters (Python `len`) for everything before the Sources block, hashtag line included. The prompt targets about 1450.
- Hashtags: normalized in code (one leading `#`, word characters only, case-insensitive dedupe, capped at 12). The validator requires 8–12 unique `#\w+` tags on the last line before Sources, and no hashtags in the hook, story or CTA.
- No `[n]` markers anywhere in the post: code strips them, and the validator fails if any remain.
- Sources: the URLs of the sources the draft's `source_numbers` name (out-of-range numbers dropped, deduped, at most 5, in source order). If none are valid, the first 3 sources are used. The validator requires 1–5 unique URLs, each one found in `state["sources"]`.
- `content_agent/validators.py` gains `validate_linkedin(post, sources) -> list[str]` (an empty list means valid). The writer, the tests and the live check all use it.
- Revision loop: up to 2 revisions with the validator's failures and the current character count. If the post still fails, the last draft is returned and each failed check is appended to `errors`.
- Entry 1's LLM error convention applies in the router and the writer. Tests run offline with a fake LLM and mocked SerpAPI.

**Never:**
- No markdown headings or `**` in the post (LinkedIn shows plain text). No image work (entry 6). No change to query generation, search, synthesis or the blog writer.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| LinkedIn request | intent linkedin, sources, router picks linkedin | `final_output` passes `validate_linkedin`; `target_format=linkedin` | — |
| Blog / research request | router picks blog / report | blog post / strategist report, as in entry 4, with no deferred-writer note | — |
| LinkedIn, no sources | `sources=[]` | router not called; strategist no-sources report | — |
| Too short, fixed on revision | first draft 900 chars, revision 1450 | revised post returned, `errors` unchanged | — |
| Still invalid after 2 revisions | every draft fails | last draft returned; one `errors` entry per failed check | — |
| Messy draft | `[2]` in story, `#AI` twice, 14 tags, `source_numbers=[99]` | markers stripped, tags deduped and capped at 12, Sources = first 3 URLs | — |
| Router or writer LLM fails | OpenAI or parse error | `intent=error`, readable message, run ends | entry 1 convention |

</frozen-after-approval>

## Code Map

- `content_agent/validators.py` -- add `validate_linkedin` plus small helpers the tests import (`linkedin_post_text` for the part before `Sources:`, `hashtags`). Reuse `_CITATION`. Leave the blog checks untouched.
- `content_agent/linkedin.py` (new) -- `linkedin_writer(state)`. `LinkedInDraft(hook, story, cta, hashtags: list[str], source_numbers: list[int])`; code strips citations, removes `#` from the prose parts, normalizes tags, assembles the post, then validates and revises. Follow `blog.py`: `_invoke` helper, only the LLM call inside the `try`, revision at temperature 0.2. Reuse `research._LLM_ERRORS`, `_llm_failure`, `_clean_citations`, `_topic`; call `llm.get_llm` through the module.
- `content_agent/router.py` -- `PostResearchDecision.target_format` gets `"linkedin"`; update `POST_RESEARCH_PROMPT`. `route_after_research` returns `linkedin_writer` for `linkedin`.
- `content_agent/state.py` -- update the `target_format` comment.
- `content_agent/graph.py` -- add the `linkedin_writer` node, router edge and `linkedin_writer -> END`; update the docstring diagram.
- `content_agent/strategist.py` -- remove `_DEFERRED_WRITERS` and the deferred-writer note in `_notes`, since every format now has a writer.
- `tests/test_strategist.py`, `tests/test_blog.py`, `tests/test_research.py` -- drop or rewrite the "LinkedIn writer is not built yet" assertions; a linkedin intent with a `report` decision still gets the report.
- `tests/test_validators.py` -- add a LinkedIn draft/post fixture builder and unit tests for each rule.
- `tests/test_linkedin.py` (new) -- one graph test per matrix row.

## Tasks & Acceptance

**Execution:**
- [x] `content_agent/validators.py` -- `validate_linkedin` -- one definition of "valid" for the code, the tests and the live check.
- [x] `content_agent/router.py`, `content_agent/state.py` -- `linkedin` routing option -- R2.
- [x] `content_agent/linkedin.py` -- writer with assembly and revision loop -- R5.
- [x] `content_agent/graph.py`, `content_agent/strategist.py` -- wiring and note removal.
- [x] `tests/test_validators.py`, `tests/test_linkedin.py`, `tests/test_strategist.py`, `tests/test_blog.py`, `tests/test_research.py` -- offline proof of every matrix row and validator rule.

**Acceptance Criteria:**
- Given no API keys and no network, when `uv run pytest` runs, then all tests pass.
- Given real keys, when "Write a LinkedIn post about AI in B2B marketing" runs under `langgraph dev`, then `validate_linkedin(final_output, sources)` returns `[]`.

## Implementation Notes

- Implemented directly in the session (no implementation subagent). The Code Map's `tests/test_research.py` item needed no change: it has no deferred-writer assertions.
- The validator finds hook, story and CTA by paragraph position. The writer adds `_draft_failures` (empty hook or CTA after cleaning) to the validator's list, so a missing part triggers a revision instead of a story paragraph standing in for it.
- Fixtures: `tests/test_validators.py` has `make_story` / `linkedin_draft` / `make_linkedin`, which produce exact character totals; `tests/test_linkedin.py` imports them.
- Live (gpt-4o-mini, 2026-10-10): 3 of 3 runs of "Write a LinkedIn post about AI in B2B marketing" returned `validate_linkedin == []` with no errors (1424, 1487 and 1488 characters), run through `graph.invoke` with the `.env` keys.

## Plan Change Log

## Review Triage Log

**Pass 1 (quick lens)**: high 0 / medium 1 / low 4 / false 1 / maybe-false 0

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | An empty hook or CTA (after cleaning) passes: a story paragraph is checked in its place | medium | patch | Verified: `_assemble` drops empty parts and the validator works by position. Patch: `_draft_failures` adds "The hook/cta is empty." to the failures, so a revision runs; tested. |
| 2 | A hashtag block spread over several lines passes | low | patch | Verified: `split()` also splits on newlines. Direct fix: a newline in the tag paragraph fails; tested. |
| 3 | No blank line required before `Sources:`; non-URL lines under Sources ignored | low | patch | Verified against the plan's shape. Direct checks added; tested. |
| 4 | `linkedin_draft` length is wrong when `hook`/`cta` are overridden | low | patch | Verified (about 1415 instead of 1450). `fixed` now uses the actual fields. |
| 5 | The markdown/citation validator test doesn't assert the specific message | low | patch | Verified. The test now asserts the exact single failure per case. |
| 6 | Code Map's `tests/test_research.py` not in the diff | false | reject | That file has no "not built yet" assertions, so no change was needed (noted in Implementation Notes). |

## Design Notes

Hook, CTA and hashtags are checked structurally (paragraph position, length, tag count), not for tone, because a validator can't judge whether a hook is compelling. That part is left to the prompt. Assembled shape:

```
<hook>

<story paragraph(s)>

<cta>

#Tag1 #Tag2 ... #Tag8-12

Sources:
- https://...
```

## Verification

**Commands:**
- `env -u OPENAI_API_KEY -u SERPAPI_API_KEY uv run pytest -q` -- expected: all pass offline.

**Manual checks (if no CLI):**
- With real keys, run a LinkedIn request through `langgraph dev`, then run `validate_linkedin` on the returned post: expect `[]`.
