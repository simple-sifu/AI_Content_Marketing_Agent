---
title: 'Blog posts must cite sources inline'
type: 'bugfix'
ticket: ''
created: '2026-10-10'
status: 'built'
baseline_revision: '1152f90b9dd3f5120ed40d2ea00ce448eafe47c4'
route: 'oneshot'
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

**Problem:** A live blog post (2026-10-10, "Write a blog post about remote work tools") had no inline `[n]` citations, yet `validate_blog` returned `[]`. The validator only checks that markers which are present map to a source; it never requires any. The epic's promise that output is research-backed, with citations, isn't enforced for blogs.

**Approach:** `validate_blog` requires the body to cite its sources: at least one `[n]` per 200 body words (minimum 3), covering at least `min(2, len(sources))` distinct sources. The failure message feeds the existing revision loop, and the revision prompt gets a "How to fix" line for missing citations. The research and LinkedIn paths are unchanged (LinkedIn deliberately has no inline markers).

</frozen-after-approval>

## Implementation Notes

Oneshot: about 30 lines across `content_agent/validators.py` (new check plus constants) and `content_agent/blog.py` (revision hint), plus test updates. The shared `make_body` fixture cites `[1]` once per paragraph, so its default becomes `[1][2]`; tests that pass their own `cite` are adjusted where they expect a valid post.
- As built: `make_body` now cites mid-paragraph and at the end, and its default cite is `[1][2]`. `test_citations_must_map_to_sources` prefixes `[1][2]` to the bad marker. New tests: no citations, single-source citations, and scaling with one source.
- Live (2026-10-10, "Write a blog post about remote work tools"): `validate_blog == []`, `errors == []`, 1,090 body words, 17 inline citations to 9 of 14 sources.

## Review Triage Log

**Pass 1 (quick lens)**: high 0 / medium 0 / low 5 / false 0 / maybe-false 0

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | No boundary test; `test_citation_minimum_scales_with_length_and_sources` doesn't vary length | low | patch | Verified. Renamed to `test_one_source_needs_only_one_distinct_source`; added `test_citation_minimum_boundary` (500/800/1000/1400 words, one below and at each threshold). |
| 2 | "One per 200 words" uses floor, which isn't stated | low | patch | Verified (1,199 words needs 5). The floor is intended (lenient); the constant's comment now says so and the boundary test pins it. |
| 3 | With zero sources, every post fails with a "0 different sources" message | low | reject | Unreachable: `graph._route_after_synthesize` never sends a run without sources to `blog_writer`. A guard would add a branch for a state the program can't reach. |
| 4 | Repeated markers count; no per-section spread enforced | low | reject | The plan asks for a count and distinct sources, not spread. The revision prompt asks for citations in every section, and the live post cited 9 of 14 sources 17 times. A spread check adds complexity for a rare pattern. |
| 5 | One-source tests now rely on `_clean_body` stripping `[2]` from the default fixture | low | reject | The tests are correct and exercise real cleaning; changing them is cosmetic. |

## Verification

**Commands:**
- `env -u OPENAI_API_KEY -u SERPAPI_API_KEY uv run pytest -q` -- expected: all pass.

**Manual checks (if no CLI):**
- One live blog request: `validate_blog` returns `[]`, and the body contains inline `[n]` citations.
