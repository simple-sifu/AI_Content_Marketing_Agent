---
title: 'Image Generator with model fallback chain'
type: 'feature'
ticket: '6'
created: '2026-10-10'
status: 'built'
baseline_revision: 'c211c1adb39d9a74878a0fc0615d3206f8c26223'
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

**Problem:** Image requests stop after classification with "The image generator is not built yet".

**Approach:** Route image intents straight to a new Image Generator node (no research). It has the LLM enhance the prompt, tries gpt-image-1, then DALL-E 3, then DALL-E 2 on refusal or error, saves the image as a PNG with Pillow under `outputs/`, and reports the file path and the model that answered.

## Boundaries & Constraints

**Always:**
- Prompt enhancement: one structured LLM call (`ImagePrompt(prompt)`) that turns the request and topic into a detailed visual prompt of at most 800 characters. Entry 1's LLM error convention applies: a failure ends the run with `intent=error`.
- Chain, in order: `gpt-image-1`, `dall-e-3`, `dall-e-2`, each called with the same parameters: `n=1`, `size="1024x1024"`, and no `response_format` (the API rejects it as `unknown_parameter`; user's decision, 2026-10-10). A response without base64 image data counts as that model's failure. The prompt is truncated to each model's limit (DALL-E 2: 1000 characters).
- A step falls back to the next model on any `openai.OpenAIError` (a content-policy refusal, an unverified org, a model that isn't served, a rate limit or a server error), or when the response has no image data or Pillow can't decode it.
- Save: decode with Pillow and save as PNG to `<IMAGE_OUTPUT_DIR or "outputs">/<UTC timestamp>-<topic slug>-<6 hex>.png`, creating the folder if needed. Add `outputs/` to `.gitignore` and `pillow` to `pyproject.toml` (with an updated `uv.lock`).
- State on success: `image_path`, `image_model`, `image_prompt`; `final_output` is markdown naming the saved path, the model and the enhanced prompt. Each failed earlier step is appended to `errors` as `image_generator: <model> failed (<ExceptionClass>)`.
- Messages and `errors` use exception class names only, never exception text (the same rule as entry 1's `llm_error`).
- The OpenAI images client is built in one place (`llm.get_image_client()`) so tests can replace it. Tests are offline: a fake LLM and a fake images client, saving to `tmp_path`.

**Never:**
- No research, no post-research router and no strategist for image intents. No resizing (user's decision, 2026-10-10: save the model's 1024x1024 image only), editing or variations. No upload anywhere. No change to the research, blog or LinkedIn paths.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| gpt-image-1 answers | image intent, first model returns base64 PNG | PNG saved; `image_model=gpt-image-1`; `errors=[]`; one images call | — |
| Fall back to DALL-E 3 | gpt-image-1 raises `PermissionDeniedError` | saved from dall-e-3; `errors` has the gpt-image-1 line | — |
| Fall back to DALL-E 2 | first two raise (e.g. `BadRequestError`, `NotFoundError`) | saved from dall-e-2; two `errors` lines; prompt sent to DALL-E 2 ≤ 1000 chars | — |
| Unusable response | a model returns no data or bytes Pillow can't decode | treated as that model's failure; the next model is tried | — |
| All models fail | all three raise | `intent=error`; readable message listing each model and exception class; no file written; three `errors` lines | — |
| Enhancement fails | LLM raises an OpenAI or parse error | `intent=error`, entry 1 message; no images call | entry 1 convention |
| Save fails | writing the PNG raises `OSError` | `intent=error`, "could not save the image" message; `errors` gets `image_generator: OSError` | — |
| Other intents | research / blog / linkedin / empty | unchanged; image generator never runs | — |

</frozen-after-approval>

## Code Map

- `content_agent/images.py` (new) -- `image_generator(state)`. `ImagePrompt` structured output via `llm.get_llm` (called through the module); `IMAGE_MODELS` with per-model prompt limits; `_generate(client, model, prompt)`; `_save(png_bytes, topic) -> Path` using `PIL.Image`. Reuse `research._LLM_ERRORS`, `_llm_failure`, `_topic`.
- `content_agent/llm.py` -- add `get_image_client()` returning `openai.OpenAI()`, built lazily the way `get_llm` is, so imports never need a key.
- `content_agent/router.py` -- `route_after_query_handler`: `image` goes to `image_generator`. `SUCCESS_TEMPLATE` / `_WRITERS` ("not built yet") are now unreachable for every intent: remove them and drop `final_output` from the query handler's success return. The empty and error returns are unchanged.
- `content_agent/state.py` -- add `image_prompt`, `image_path`, `image_model` (written only on image runs).
- `content_agent/graph.py` -- add the `image_generator` node, the edge from `query_handler`, and `image_generator -> END`; update the docstring diagram.
- `pyproject.toml`, `uv.lock`, `.gitignore` -- `pillow`; `outputs/`.
- `tests/test_query_handler.py` -- `test_classified_requests` stops asserting the intent/topic `final_output`; image routes to `image_generator`; `test_image_success_ending_matches_design` is replaced by the image tests.
- `tests/test_images.py` (new) -- a fake images client (a list of outcomes, one per call: bytes, `None` or an exception; records model and kwargs), a real tiny PNG built with Pillow as base64, a `tmp_path` output folder via `IMAGE_OUTPUT_DIR`. One graph test per matrix row.

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml`, `uv.lock`, `.gitignore` -- add pillow (`uv add pillow`), ignore `outputs/`.
- [x] `content_agent/llm.py`, `content_agent/state.py` -- image client switch point and state fields.
- [x] `content_agent/images.py` -- enhancement, fallback chain, Pillow save -- R6.
- [x] `content_agent/router.py`, `content_agent/graph.py` -- route image intents to the node -- R1.
- [x] `tests/test_images.py`, `tests/test_query_handler.py` -- offline proof of every matrix row.

**Acceptance Criteria:**
- Given no API keys and no network, when `uv run pytest` runs, then all tests pass.
- Given a real OpenAI key, when "Make an image of a sunrise over a city" runs under `langgraph dev` (or `graph.invoke`), then a PNG Pillow can open exists at `image_path`, and `image_model` names the model that answered (recorded in Implementation Notes).

## Implementation Notes

- Implemented directly in the session. `tests/conftest.py` gains `png_b64`, `FakeImages` and the `use_images` fixture (which points `IMAGE_OUTPUT_DIR` at `tmp_path`). `tests/test_research.py::test_image_intent_skips_research` was updated as well, since it asserted the old "not built yet" ending.
- A missing key makes `openai.OpenAI()` raise at construction. That is caught before the chain and reported with entry 1's convention (`image_generator: OpenAIError`, "Check OPENAI_API_KEY").
- `query_handler` clears `image_prompt` / `image_path` / `image_model` at the start of every run (`_IMAGE_RESET`), like `generate_queries`' research reset.
- Live (2026-10-10, before the account change): every model failed. gpt-image-1 returned `403 model_not_found` (the project doesn't have access; it exposes 8 models, none for images). dall-e-3 and dall-e-2 first returned `400 unknown_parameter` for `response_format`; without it, the API says they "do not exist". The chain and the all-failed message behaved as designed. The live acceptance criterion is pending the user enabling gpt-image-1 for the project.
- Live (2026-10-10, after the user switched `.env` to a key from their Default project, where gpt-image-1 is enabled): "Make an image of a sunrise over a city" returned `intent=image`, `errors=[]`, `image_model=gpt-image-1`. A 1024x1024 PNG that Pillow opens was saved at `outputs/20261010T164727Z-sunrise-over-a-city-0a7ebe.png` and shows a city skyline at sunrise. The earlier failures came from the old key, which belonged to a different project (`proj_mj9Z…`) with an 8-model allowlist.

## Plan Change Log

- 2026-10-10, live run (not a review finding): the images endpoint rejected `response_format` as `unknown_parameter`, and the API reported `dall-e-3` / `dall-e-2` as "does not exist". With the user's approval the frozen chain bullet changed: no `response_format`, and a response without base64 counts as a failure. KEEP: chain order, fallback on any `OpenAIError` or unusable image, class-name-only messages.

## Review Triage Log

**Pass 1 (quick lens)**: high 0 / medium 1 / low 4 / false 0 / maybe-false 0; plus 1 verification (resolved)

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | Live acceptance criterion not recorded | — | resolved | Was blocked by the old key's project. Rerun with the new key passed (gpt-image-1, PNG saved); recorded in Implementation Notes. |
| 2 | Old `image_path` / `image_model` survive on a reused thread after a failed image run or on later runs | medium | patch | Reviewer reproduced it with `InMemorySaver`. `query_handler` now clears the image fields on every return; tested with a two-run thread. |
| 3 | Save-failure `errors` entry is the subclass name, not the matrix's `image_generator: OSError` | low | patch | Verified. The entry is now `image_generator: OSError`; the subclass stays in the message. |
| 4 | Save-failure message wording differs from the matrix ("could not save the image") | low | patch | Verified. Message reworded. |
| 5 | A decoded image Pillow can't write as PNG (e.g. CMYK) reports a disk failure | low | patch | Verified that Pillow raises OSError for CMYK PNG writes. `_generate` converts modes PNG can't hold to RGBA; tested with a CMYK image. |
| 6 | The "Other intents" row isn't tested through the graph | low | patch | Verified. The test now runs research/blog/linkedin through `graph.invoke` and asserts no images call. |

## Design Notes

The fake client mirrors the SDK shape the node reads: `client.images.generate(**kwargs).data[0].b64_json`. One decoding path serves the whole chain; a model that answers without `b64_json` falls through to the next:

```python
IMAGE_MODELS = (
    ("gpt-image-1", 32000),
    ("dall-e-3", 4000),
    ("dall-e-2", 1000),
)
```

## Verification

**Commands:**
- `env -u OPENAI_API_KEY -u SERPAPI_API_KEY uv run pytest -q` -- expected: all pass offline.

**Manual checks (if no CLI):**
- With a real key, run an image request; open the PNG at `image_path` and note `image_model`.
