# AI Content Marketing Agent

**[See it in action →](https://simple-sifu.github.io/AI_Content_Marketing_Agent/)** Real, unedited outputs for all four formats: a research report, an SEO blog post, a LinkedIn post and an image.

A LangGraph agent that turns a single request into content you can publish. Ask for research, a blog post, a LinkedIn post or an image, and it sends the request to the right specialist:

| Ask for | You get |
|---------|---------|
| Research ("Give me an overview of AI in B2B marketing") | A markdown research report: executive summary, key findings and numbered sources |
| A blog post ("Write a blog post about remote work tools") | A long-form SEO post: meta description, one H1, H2/H3 sections, 1–2% keyword density, `[n]` citations and a Sources list |
| A LinkedIn post ("Write a LinkedIn post about AI in B2B marketing") | A 1300–1600 character plain-text post with a hook, story, call to action, 8–12 hashtags and a short list of source URLs |
| An image ("Make an image of a sunrise over a city") | A PNG saved to `outputs/`, plus the model that made it and the prompt it used |

Research, blog and LinkedIn content all come from the same research step: three SerpAPI searches whose results are summarized with citations. Every `[n]` citation points to a source that a search actually returned. The blog and LinkedIn writers check their output against format rules and ask the model to fix the draft (up to twice) before returning it.

## How it works

```
request -> query_handler --(research | blog | linkedin)--> Deep Research
                         |--(image)--> image_generator -> PNG in outputs/
                         \--(empty | error)--> reply

Deep Research: generate_queries -> run_searches (SerpAPI) -> synthesize (cited findings)
  --(sources found)--> post_research_router --(blog)------> blog_writer
  |                                         |--(linkedin)--> linkedin_writer
  |                                         \--(report)----> content_strategist
  \--(no sources)--> content_strategist (short "no sources" report)
```

The code is in `content_agent/`. The graph is in `content_agent/graph.py`, and `langgraph.json` points LangGraph at it.

## Prerequisites

- **Python 3.12** and **[uv](https://docs.astral.sh/uv/)**
- **An OpenAI API key.** Every step uses the chat model (`gpt-4o-mini` by default). Images use `gpt-image-1`, which needs two things:
  - The key's project must allow it: on platform.openai.com go to **Settings → Project → Limits** and allow gpt-image-1, or allow all models.
  - Your organization must be verified: **Settings → Organization → General**.
  - The key belongs to the project it was created in. If image requests fail with `PermissionDeniedError`, the key may be from a project that doesn't allow gpt-image-1.
- **A SerpAPI key** ([serpapi.com](https://serpapi.com)) for web research.
- Optional: a LangSmith key for tracing.

## Setup

```bash
git clone https://github.com/simple-sifu/AI_Content_Marketing_Agent.git
cd AI_Content_Marketing_Agent
uv sync
cp .env.example .env
```

Then open `.env` and fill in `OPENAI_API_KEY` and `SERPAPI_API_KEY`. The other settings are optional and explained in the file. `.env` is ignored by git and kept out of Docker builds, so don't commit or share it.

## Run locally

```bash
uv run langgraph dev
```

This starts the API at `http://127.0.0.1:2024` and opens LangGraph Studio in your browser. In Studio, pick the `content_agent` graph and send the input `{"request": "<what you want>"}`. For example:

- `Give me an overview of AI in B2B marketing`: research report
- `Write a blog post about remote work tools`: SEO blog post
- `Write a LinkedIn post about AI in B2B marketing`: LinkedIn post
- `Make an image of a sunrise over a city`: PNG in `outputs/`

The result is in `final_output`. The state also shows:

- `intent`, `topic` and `target_format`: how the request was routed
- `sources` and `findings`: what research found
- `image_path` and `image_model`: for image requests
- `errors`: problems from this run only, such as a failed search, a format check that still failed after the rewrites, or an image model that refused

If an OpenAI call fails, the run stops with a readable message instead of crashing. Messages never include API keys.

Use `uv run langgraph dev --no-browser` to skip opening Studio.

## Tests

```bash
uv run pytest
```

The tests run offline. The LLM, SerpAPI and the images API are replaced with fakes, so no keys or network are needed and nothing is billed.

## Deploy to LangGraph Cloud

The project is ready for LangGraph Cloud (LangGraph Platform, managed from LangSmith). `langgraph.json` declares the graph, the Python version and the dependencies, which are installed from `pyproject.toml`.

1. **Build the image locally (optional check).** Start Docker Desktop, then run:

   ```bash
   uv run langgraph build -t content-agent
   ```

   `.dockerignore` keeps `.env`, `outputs/`, `.venv/` and other local files out of the image. To preview the generated Dockerfile without Docker, run `uv run langgraph dockerfile /tmp/Dockerfile`.

2. **Deploy.** Push the repo to GitHub. In LangSmith, open **Deployments → New Deployment**, connect the GitHub repository and branch, and keep `langgraph.json` as the config file.

3. **Set secrets.** Under the deployment's environment variables, add `OPENAI_API_KEY` and `SERPAPI_API_KEY`, plus `OPENAI_MODEL` or `IMAGE_OUTPUT_DIR` if you change them. Your local `.env` is never uploaded.

## Known limits

- **Images are saved to the server's local disk** (`outputs/`, or `IMAGE_OUTPUT_DIR`). On LangGraph Cloud that disk is temporary and not publicly reachable, so the reported `image_path` is only useful locally. Hosted image storage isn't built yet.
- **Image model fallback.** The agent tries `gpt-image-1`, then `dall-e-3`, then `dall-e-2`. As of October 2026 the API reports both DALL-E models as no longer available, so in practice images need gpt-image-1 access (see Prerequisites). If every model fails, the reply names each model and the error type.
- **Research quality depends on SerpAPI results.** Off-topic search results can weaken the sources, though citations always point to a real search result.
- **Not included:** a creator-facing UI (use LangGraph Studio), publishing to blog platforms or LinkedIn, and scheduling.
