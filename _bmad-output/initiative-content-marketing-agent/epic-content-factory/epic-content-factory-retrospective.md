---
epic: epic-content-factory
date: 2026-10-10
verdict: accepted-with-open-items
criteria: declared
headless: false
---

# Retrospective: Creators get research-backed blogs, LinkedIn posts, and images from one request

## Epic summary

- **Epic:** `epic-content-factory` (initiative `initiative-content-marketing-agent`), with 8 stories built in series.
- **Tickets:** all 8 are finished, with status `built` and state `review`. None is at `done`; closing the epic is `bmad-ticket`'s job, with the user's confirmation. `pending_tickets` is empty.

| Ref | Ticket | Plan range (baseline..next) | Commits (non-merge) | PR |
|-----|--------|-----------------------------|---------------------|----|
| 1.1 | Project scaffold and Query Handler | `5c88824..42d8c8a` | 1 | #1 |
| 1.2 | Deep Research agent | `42d8c8a..3ae7b8b` | 1, plus the story 3 plan commit | #2 |
| 1.3 | Content Strategist report | `3ae7b8b..2c1cba6` | 1 | #3 |
| 1.4 | SEO Blog Writer and post-research routing | `2c1cba6..cfaad79` | 1 | #4 |
| 1.5 | LinkedIn Writer | `cfaad79..c211c1a` | 1 | #5 |
| 1.6 | Image Generator with model fallback chain | `c211c1a..55fd548` | 1 | #6 |
| 1.7 | LangGraph Cloud-ready packaging and docs | `55fd548..d07940a` | 2 | #7 |
| 1.8 | Refactor sweep | `d07940a..30cd721` (head, inferred) | 1 | #8 |

- **Evidence available:** the epic file (with Done when), initiative requirements, `tickets.toml`, all 8 plans (each with a Review Triage Log from one quick-lens pass), `deferred-work.md`, git history and PRs #1–#8, `git_evidence.py` output per range, and a live behaviour check run during this retro.
- **Evidence missing:**
  - Session logs: none are kept in the repo, so the process-lesson analysis is limited to what the plans record.
  - Previous retrospective: none, since this is the initiative's first epic.
- **User focus:** live-check gaps. The analysis below weights them first.

## Findings

### Live-check gaps (user focus)

| # | Finding | Source | Disposition |
|---|---------|--------|-------------|
| L1 | **Story 1's LangSmith tracing criterion was never verified.** The plan's AC requires a `langgraph dev` run to show up in the LangSmith project. `.env` holds `LANGCHAIN_API_KEY` and `LANGCHAIN_PROJECT` but no tracing switch (`LANGSMITH_TRACING` or `LANGCHAIN_TRACING_V2`), so tracing was never on, and the plan's Implementation Notes record no trace. | `story-project-scaffold-and-query-handler-plan.md:87`; `.env` key names | **Defer** to an action item (A1). Lesson: a human-in-the-loop AC needs its result written into the plan before the plan is marked `built`. |
| L2 | **Stories 1–3 record no live result** for their "under `langgraph dev`" ACs. Their Implementation Notes have no live entry. Story 2's live run shows up only indirectly, in `deferred-work.md` (the query-quality entry). | plans 1–3, Acceptance Criteria and Implementation Notes; `deferred-work.md` entry 5 | **Accept**: the behaviour check below now covers these paths. Lesson: stories 4–8 recorded their live results in the plan; keep doing that. |
| L3 | **Live checks for stories 4, 5, 6 and 8 ran through `graph.invoke`, not the `langgraph dev` server.** Story 4's live pass rate (7 of 8) was measured before its keyword-budget fix and never rerun (PR #4 test plan). Story 5's 3 of 3 came before its review fixes. Every PR left its Studio item unchecked. | story 4 plan, Implementation Notes and PR #4; story 5 plan, Implementation Notes; PRs #5–#8 test plans | **Accept**: the behaviour check ran blog and LinkedIn through `langgraph dev` after all fixes, and both validators returned `[]`. Lesson: when a criterion says "under `langgraph dev`", run it through the server API (`/runs/wait`); it can be scripted. |
| L4 | **Story 6's plan was built on stale API assumptions.** It specified `response_format="b64_json"` for DALL-E, which the endpoint now rejects as `unknown_parameter`. DALL-E 3 and 2 return "does not exist", so 2 of the 3 models in the chain can never answer. The live check was also blocked by the API key's project (`proj_mj9Z…`, an 8-model allowlist) until the user switched keys. The epic's Notes had already listed the model availability as Unknown. | story 6 plan, Plan Change Log and Implementation Notes; epic Notes, "Unknown: … DALL-E 3 / DALL-E 2 are still served" | **Defer**, with a spec reconciliation proposed (A2). Lesson: when an epic lists an external-API Unknown, settle it with a one-call probe at planning time, before the plan is frozen. |
| L5 | **A SerpAPI query timed out during the behaviour check** (`ReadTimeout` after 30 s). Per-query isolation worked: the error was listed, and the report was built from the other 9 sources. | behaviour check below; `research.SEARCH_TIMEOUT_SECONDS` | **Accept**: the system behaved as designed. No action. |

### Aggregate views

| # | View | Finding | Source | Disposition |
|---|------|---------|--------|-------------|
| G1 | Architecture delta | **`research.py` became the shared-helpers module through private names.** `router`, `blog`, `linkedin`, `images` and `validators` import `_LLM_ERRORS`, `_llm_failure`, `_topic`, `_clean_citations` and `_CITATION` from it, and `blog` also imports `strategist._clean_title` and `_unbracket`. No ticket owned this cross-cutting layer; each story reached into the previous one's internals. | `content_agent/{router,blog,linkedin,images,validators}.py` import lines (router:15, blog:18,20, linkedin:17, images:22, validators:27) | **Defer** to A3: move them to a public `content_agent/common.py` (or into `llm.py`). |
| G2 | Duplication map | **The blog and LinkedIn writers repeat the same validate-and-revise loop**: `MAX_REVISIONS = 2`, an `_invoke` helper, the loop body, and failures appended to `errors`. Story 8 deliberately excluded merging them. | `blog.py:35,200,235`; `linkedin.py:32,174,209`; story 8 plan, Never | **Defer** to A4, together with G1. |
| G3 | Size growth | **No god class.** The largest module is `validators.py` (318 lines, two validators). The largest test file is `tests/test_research.py` (496 lines). Story 4 added the most code (1,071 lines of code and tests). | `wc -l`; `git_evidence.py` per range | **Accept.** Split `validators.py` per format only if a third validator arrives. |
| G4 | Pattern divergence | **Conventions held across stories.** All nodes follow story 1's error convention (class-name-only messages), one `get_*` switch point for each client, and tests that run offline with fakes. The state-reset rule converged on `_RUN_RESET` (stories 6 and 8). | `llm.py`; `research._llm_failure`; `router._RUN_RESET` | **Accept.** |
| G5 | Spec reconciliation | **R6 says the chain is gpt-image-1 → DALL-E 3 → DALL-E 2.** As built it matches, but two links are dead (see L4). | epic R6; `images.IMAGE_MODELS` | Spec reconciliation proposed in A2. |

### Diff-scope review

- **Scope narrowed.** `bmad-review` was not run over the whole epic diff in this retro. Each story had one quick-lens review of its own diff (8 passes: 44 findings, of which 31 were patched, 10 rejected with reasons and 3 resolved as verification or bookkeeping notes; per story, 3/7/7/7/6/6/2/6; see each plan's Review Triage Log). The seams between tickets were covered here only by G1 and G2.
- Running an epic-wide `bmad-review` (adversarial, edge-case and verification-gap lenses) over `5c88824..30cd721` remains an option; see Open questions.

## Behavior verification

Run during this retro on 2026-10-10 at `main` `30cd721`. `uv run langgraph dev --no-browser --port 2098` was started, and one request of each type was sent to `POST /runs/wait` with `assistant_id=content_agent`, using the real `.env` keys:

| Request | Result |
|---------|--------|
| "Give me an overview of AI in B2B marketing" | `intent=research`, `target_format=report`. The report has Executive Summary, Key Findings and Sources. Every `[n]` maps to one of the 9 sources. `errors` has one isolated SerpAPI `ReadTimeout` (L5). |
| "Write a blog post about remote work tools" | `intent=blog`, `target_format=blog`, `validate_blog == []`, `errors == []` |
| "Write a LinkedIn post about AI in B2B marketing" | `intent=linkedin`, `target_format=linkedin`, `validate_linkedin == []`, `errors == []` |
| "Make an image of a sunrise over a city" | `intent=image`, `image_model=gpt-image-1`, PNG at `outputs/20261010T172319Z-sunrise-over-a-city-21ed2d.png`, `errors == []` |

The offline suite was also confirmed at `main`: 182 passed (story 8 PR #8).

## Previous-retro follow-through

There was nothing to follow through on: no previous retrospective file exists. This is the first epic of `initiative-content-marketing-agent`.

## Action items

| # | Action | Owner | Kind |
|---|--------|-------|------|
| A1 | Turn on LangSmith tracing (`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT=content-agent` in `.env`). Run one request under `langgraph dev` and confirm the trace appears. Record the result in story 1's plan. | Tommy Han | Verification (closes L1) |
| A2 | Decide the image fallback chain: either replace `dall-e-3` and `dall-e-2` with image models the account can call, or update epic R6 to say the DALL-E links are retired and gpt-image-1 is the only model in practice. | Tommy Han, then the dev loop | **Spec reconciliation, proposed** (L4, G5) |
| A3 | Move the shared helpers (`_LLM_ERRORS`, `_llm_failure`, `_topic`, `_clean_citations`, `_CITATION`, `_clean_title`, `_unbracket`) into a public module and update the imports. | Dev loop (next epic or a chore story) | **Remediation, proposed** (G1) |
| A4 | Extract the shared validate-and-revise loop used by `blog.py` and `linkedin.py`. | Dev loop, with A3 | **Remediation, proposed** (G2) |
| A5 | Process: when a plan's AC says "under `langgraph dev`", verify it through the server API (scripted `/runs/wait`, as in this retro) and record the result in the plan before marking it `built`. Probe every external-API Unknown with a single call during planning. | Planning (`bmad-build` step 2) | **Process lesson** (L1–L4) |

## Acceptance verdict

**accepted-with-open-items** (machine verdict, criteria **declared** in the epic's Done when):

1. *Research, blog, LinkedIn and image requests each return their own format through `langgraph dev`:* **met**. See Behavior verification: all four ran through the server API.
2. *Automated checks prove the blog and LinkedIn rules:* **met**. `validate_blog` and `validate_linkedin` have per-rule unit tests (`tests/test_validators.py`) and returned `[]` on the live runs.
3. *An image file is saved on a live run, and tests prove the fallback chain:* **met**. The live PNG came from gpt-image-1, and `tests/test_images.py` covers each fallback step. The DALL-E links are dead in practice (A2), but the chain and its tests match R6 as written.
4. *Every `[n]` and LinkedIn Sources URL maps to a SerpAPI source:* **met**. This is enforced in code and tests (stories 2–5), and the live research report's markers all map to its 9 sources.
5. *`langgraph build` produces a deployable image and the offline suite passes:* **met**. The user built the image (story 7 plan, Implementation Notes; no `.env` in it), and 182 tests pass.

The open items are A1–A4. None blocks the Done when criteria. A1 is a story 1 verification item, not an epic criterion. A human decision may override this verdict.

## Open questions

- Should an epic-wide `bmad-review` run over `5c88824..30cd721` to cover the seams between tickets more deeply than G1 and G2 do?
- A2: replace the DALL-E links with a live model, or reconcile R6 to reality?
- Should the 8 tickets be marked `done` and the epic closed (`bmad-ticket`) now, or after A1?
