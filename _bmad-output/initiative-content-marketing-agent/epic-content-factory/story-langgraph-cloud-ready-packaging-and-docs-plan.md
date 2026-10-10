---
title: 'LangGraph Cloud-ready packaging and docs'
type: 'chore'
ticket: '7'
created: '2026-10-10'
status: 'built'
baseline_revision: '55fd548d42458dc31bd3d3b86acc81c7647ef9e3'
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

**Problem:** The graph runs locally, but nothing shows a newcomer how to set it up, and nothing confirms the project builds into a deployable LangGraph image without leaking local secrets or files into it.

**Approach:** Check that the packaging is complete (dependencies, `.env.example`), keep local-only files out of the Docker build context, and write a README covering setup, `langgraph dev`, tests and deploying to LangGraph Cloud. Prove it with a generated Dockerfile, a fresh-clone run and `langgraph build`.

## Boundaries & Constraints

**Always:**
- `pyproject.toml` lists every third-party package `content_agent/` imports. Today that's langgraph, langchain-core, langchain-openai, openai, python-dotenv, pydantic, google-search-results (`serpapi`) and pillow (`PIL`), and `langgraph.json` installs them through `"dependencies": ["."]`. Change either file only if the check finds a gap.
- `.env.example` names every environment variable the code reads: `OPENAI_API_KEY`, `OPENAI_MODEL`, `SERPAPI_API_KEY`, an optional `IMAGE_OUTPUT_DIR` (new) and the optional LangSmith trio. Each has a one-line comment, and no real values.
- New `.dockerignore` keeps `.env`, `.venv/`, `outputs/`, `.git/`, caches, `.langgraph_api/`, `_bmad/` and `_bmad-output/` out of the image. `langgraph build` copies the project directory into the image, so without this a local `.env` with real keys would be baked in.
- New `README.md`:
  - what the agent does (four formats, one request)
  - a short graph diagram
  - prerequisites: Python 3.12, uv, OpenAI and SerpAPI keys, gpt-image-1 project access
  - setup: `uv sync`, copy `.env.example` to `.env`
  - running: `uv run langgraph dev`, with one example request per format and what comes back
  - offline tests: `uv run pytest`
  - deploying: `uv run langgraph build -t content-agent`, then LangGraph Cloud (LangSmith deployments) from the GitHub repo, with the env vars set as deployment secrets
  - known limits: images go to the server's local disk (ephemeral on Cloud); DALL-E 3/2 are reported as retired, so gpt-image-1 needs project access and a verified organization
  - Every command in it is run once during verification.
- No change to `content_agent/` behaviour, and the offline test suite still passes.

**Never:**
- No real LangGraph Cloud deployment, no CI pipeline, no Dockerfile committed (`langgraph build` generates its own), no new features or image storage changes.

</frozen-after-approval>

## Code Map

- `langgraph.json` -- graph `content_agent` at `./content_agent/graph.py:graph`, `env: .env`, Python 3.12, `dependencies: ["."]`. Already correct; leave it unless the build shows otherwise.
- `pyproject.toml` -- runtime deps listed above; dev group has pytest, httpx, `langgraph-cli[inmem]` (provides `langgraph dev`, `build` and `dockerfile`).
- `.env.example` -- add `IMAGE_OUTPUT_DIR` (commented, default `outputs`) and a pointer to gpt-image-1 access for `OPENAI_API_KEY`. Env reads: `llm.py` (`OPENAI_MODEL`; the OpenAI clients read `OPENAI_API_KEY`), `research.py` (`SERPAPI_API_KEY`), `images.py` (`IMAGE_OUTPUT_DIR`).
- `.dockerignore` (new), `README.md` (new).
- `.gitignore` -- already ignores `.env`, `outputs/` and caches; add `.ruff_cache/`.
- Graph shape for the README diagram: the docstring at the top of `content_agent/graph.py`.

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml`, `langgraph.json` -- check every runtime import is a declared dependency (fix only if needed).
- [x] `.env.example`, `.gitignore`, `.dockerignore` -- complete the env template; keep secrets and local files out of git and the image.
- [x] `README.md` -- setup, run, test, deploy and limits, as above.

**Acceptance Criteria:**
- Given no API keys and no network, when `uv run pytest` runs, then all tests pass.
- Given the repo, when `uv run langgraph dockerfile <tmp>/Dockerfile` runs, then it succeeds and the Dockerfile installs the project from `langgraph.json`.
- Given a fresh `git clone` of the branch into a temp folder, when the README's setup steps run with a copied `.env`, then `uv run pytest` passes and `uv run langgraph dev` serves the API (its `/ok` endpoint answers).
- Given Docker running (user-assisted), when `uv run langgraph build -t content-agent` runs, then the image builds, and `.env` is not inside it.

## Implementation Notes

- Dependency check: every third-party import in `content_agent/` was already declared, so `pyproject.toml` and `langgraph.json` are unchanged.
- `uv run langgraph dockerfile` produced `ADD . /deps/AI_Content_Marketing_Agent` and then `uv pip install -e .`, which confirmed that `.dockerignore` was needed to keep `.env` out of the image.
- Fresh clone (2026-10-10): `git clone --branch story-7-packaging-and-docs` of commit 8d8bcd9 into the scratchpad, followed by the README setup (`uv sync`, `cp .env.example .env`, keys copied in). `uv run pytest -q`: 168 passed. `uv run langgraph dev --no-browser --port 2099`: `/ok` returned `{"ok":true}` and assistants search listed `content_agent`. The first pass applied a patch to a clone; it was redone from the committed branch after review.
- README commands not run by the agent: `git clone` from GitHub (the local clone stands in until the branch is pushed), and `langgraph build` plus the Deploy steps. These need Docker or the user's LangSmith account; the Docker build is the user's check.
- Docker (2026-10-10, user-run build): `uv run langgraph build -t content-agent` produced `content-agent:latest` (1.09GB). Inside it, `/deps/AI_Content_Marketing_Agent` holds only `.dockerignore`, `.env.example`, `.python-version`, `README.md`, `content_agent/`, `langgraph.json`, `pyproject.toml`, `tests/` and `uv.lock`. `find /deps -name .env` found nothing. The graph imports with Pillow and serpapi installed, and lists all 9 nodes.

## Plan Change Log

## Review Triage Log

**Pass 1 (quick lens)**: high 0 / medium 0 / low 1 / false 0 / maybe-false 0; plus 1 verification-gap note

| # | Finding | Verdict | Route | Evidence / action |
|---|---------|---------|-------|-------------------|
| 1 | README says every writer validates and revises; the strategist doesn't | low | patch | Verified: `strategist.py` has no validator or revision loop. The sentence now names the blog and LinkedIn writers only. |
| 2 | Verification unrecorded; fresh clone used an applied patch, not the branch | — | resolved | Committed, then recloned the branch and reran setup, tests and `/ok` (Implementation Notes). The user ran the Docker build afterwards and it passed (Implementation Notes). |

## Verification

**Commands:**
- `env -u OPENAI_API_KEY -u SERPAPI_API_KEY uv run pytest -q` -- expected: all pass.
- `uv run langgraph dockerfile <scratch>/Dockerfile` -- expected: generated, installs `.`.
- Fresh clone into the scratchpad, then `uv sync`, `uv run pytest -q`, and `uv run langgraph dev --no-browser` with `curl localhost:2024/ok` -- expected: tests pass, `/ok` answers.

**Manual checks (if no CLI):**
- With Docker Desktop running: `uv run langgraph build -t content-agent` succeeds, then `docker run --rm --entrypoint sh content-agent -c 'find / -name .env -path "*deps*" 2>/dev/null'` prints nothing.
