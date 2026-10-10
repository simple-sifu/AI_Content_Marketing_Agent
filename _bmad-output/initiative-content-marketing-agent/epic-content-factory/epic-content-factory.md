---
type: epic
title: "Creators get research-backed blogs, LinkedIn posts, and images from one request"
parent: initiative-content-marketing-agent
covers: []
after: []
assignee: ""
risk: medium
---

# Creators get research-backed blogs, LinkedIn posts, and images from one request

## Description

A solo creator or small marketing team types one request and the LangGraph content factory routes it to the right specialist: a cited research report, an SEO blog post, a LinkedIn post, or a generated image. Research-backed formats reuse the Deep Research agent's cited findings, so every output rests on sources rather than invention. The whole graph runs locally under `langgraph dev` and is packaged so it can deploy to LangGraph Cloud.

## Outcome

A creator gets publish-ready content in any of the four formats from a single request in minutes instead of hours; the signal is each format passing its own rule checks (citations, SEO structure, LinkedIn length and parts, an image file) on a live run.

## Requirements

- R1: The Query Handler classifies each request as research, blog, LinkedIn, or image. (brief, Proposed Solution, Query Handler)
- R2: After research, an LLM-based router decides whether to write a blog post, a LinkedIn post, or a research summary. (brief, Proposed Solution, router paragraph)
- R3: The Deep Research agent generates multiple strategic search queries, runs them through SerpAPI, and synthesizes findings with source citations. (brief, Deep Research Agent; External APIs)
- R4: The SEO Blog Writer produces long-form content with target-keyword density, a meta description, and H1/H2/H3 structure. (brief, SEO Blog Writer)
- R5: The LinkedIn Writer produces 1300–1600 character posts with a hook, story, CTA, and 8–12 hashtags. (brief, Linkedin Writer)
- R6: The Image Generator enhances the user's prompt and generates an image via the fallback chain gpt-image-1 → DALL-E 3 → DALL-E 2, handling the result with Pillow. (brief, Image Generator; Tech Stack; Heads up)
- R7: The Content Strategist formats research into a readable report when no specific format was requested. (brief, Content Strategist)
- R8: The graph runs under `langgraph dev` and is LangGraph Cloud-ready. (brief, router paragraph)

## Done when

1. Through `langgraph dev`, a research, a blog, a LinkedIn, and an image request each return their own format end to end.
2. Automated checks prove blog output has one H1, H2/H3 sections, a meta description, and keyword density in the agreed range, and LinkedIn output is 1300–1600 characters with hook, story, CTA, and 8–12 hashtags.
3. An image request saves an image file on a live run, and tests prove the chain falls back gpt-image-1 → DALL-E 3 → DALL-E 2 on refusal.
4. Every `[n]` citation in research-backed output, and every URL in the LinkedIn Sources list, maps to a source SerpAPI returned.
5. `langgraph build` produces a deployable image and the offline test suite passes.

## Boundaries

One capability in one repo with one owner: the content factory graph in `content_agent/`. Not a UI, not publishing to blog or LinkedIn platforms, not scheduling, not an actual LangGraph Cloud deployment (Cloud-ready only).

## References

- parent — _bmad-output/initiative-content-marketing-agent/brief-content-marketing-agent/brief-content-marketing-agent.md, all sections (the requirement source; R1–R8 above cite it)
- removed build — git commit 155fcac (router, research, strategist built before this epic existed; removed at the user's request, recoverable from history)
- deferred — _bmad-output/initiative-content-marketing-agent/deferred-work.md (its blog, LinkedIn, image, and OpenAI-error entries came from the removed build; the first three are now entries 4–6)

## Notes

- Decision: model is `OPENAI_MODEL`, default `gpt-4o-mini`; 3 SerpAPI queries per request (user's decisions, 2026-10-10).
- Decision: the first build (commit 155fcac) is removed and the project is rebuilt story by story from this epic; removal is a new commit, not a history rewrite (user's decision, 2026-10-10).
- Decision: entry 1 is only the scaffold plus the Query Handler — the tracer bullet through uv, LangGraph state, an LLM call, and `langgraph dev` (user's decision, 2026-10-10).
- Decision: entries run in series because each adds a node or branch to `graph.py` and the routers; entry 7 follows the agents so it packages every dependency they add (2026-10-10).
- Decision: until a format's agent exists, its requests end at the furthest stage built — entry 1's message naming intent and topic, then from entry 3 the research report for blog and LinkedIn; each agent's entry replaces that ending for its format (2026-10-10).
- Lesson from the removed build (its review found these; entries 2–3 must not repeat them): SerpAPI sends the key as a URL parameter, so network-error text leaks it — redact before any error reaches output; enforce `[n]` citations in code on the summary as well as findings; do not use an `operator.add` reducer for per-run fields like `errors`, since `langgraph dev` threads keep state across runs; OpenAI call failures need handling.
- Decision: an empty or whitespace-only request is answered with a prompt for a topic, without an LLM call (user confirmed, 2026-10-10).
- Decision: blog keyword density target is 1–2% for the primary keyword, entry 1's `topic` (user confirmed, 2026-10-10).
- Decision: Matplotlib is not used; Pillow handles saving and resizing images (user confirmed, 2026-10-10).
- Decision: entry 1 owns the LLM error convention (OpenAI failures caught into a per-run `errors` list with a readable message); entries 2–6 follow it (user's decision, 2026-10-10).
- Decision: LinkedIn posts carry no inline `[n]`; a short Sources list of research URLs follows the post, outside the 1300–1600 character count, so Done when 4 applies to it through those URLs (user's decision, 2026-10-10).
- Decision: optional LangSmith tracing (LANGSMITH_API_KEY, LANGSMITH_TRACING, LANGSMITH_PROJECT) is set up in entry 1's .env.example; nothing requires it (user's decision, 2026-10-10).
- Decision: the interface is LangGraph Studio via `langgraph dev`; no creator-facing UI is built (user's decision, 2026-10-10).
- Decision: Done when 3 is proven by mocked tests of each fallback step plus one live run saving an image from whichever model answers (user's decision, 2026-10-10).
- Unknown: whether the program's OpenAI org is verified for gpt-image-1, and whether DALL-E 3 / DALL-E 2 are still served on the account; entry 6 falls back on refusal and its live check records which model answered.
