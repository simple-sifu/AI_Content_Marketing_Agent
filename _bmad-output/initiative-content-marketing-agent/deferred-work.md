- source_plan: none
  summary: SEO Blog Writer agent (long-form, keyword density, meta description, H1/H2/H3) plus post-research routing to it.
  evidence: Split from the Content Marketing Agent brief; independently shippable once the core router/research graph exists.
- source_plan: none
  summary: LinkedIn Writer agent (1300-1600 char posts with hook, story, CTA, 8-12 hashtags) plus post-research routing to it.
  evidence: Split from the Content Marketing Agent brief; independently shippable once the core router/research graph exists.
- source_plan: none
  summary: Image Generator agent with prompt enhancement and gpt-image-1 -> DALL-E 3 -> DALL-E 2 fallback chain, Pillow handling.
  evidence: Split from the Content Marketing Agent brief; largely independent of research, needs only the core router.
- source_plan: `_bmad-output/initiative-content-marketing-agent/plan-core-router-research-graph.md`
  summary: OpenAI call failures (missing OPENAI_API_KEY, API errors, rate limits) are not caught in query_handler, generate_queries, or synthesize, so the run fails with a raw exception.
  evidence: Flagged by the implementer at hand-back; the structured-output `.invoke` calls in router.py and research.py have no error handling, and the I/O matrix did not cover this case.
- source_plan: `_bmad-output/initiative-content-marketing-agent/epic-content-factory/story-deep-research-agent-plan.md`
  summary: Research query quality — give the query prompt today's date (the model wrote "2023" into queries) and filter off-topic SerpAPI results before synthesis.
  evidence: Live run on 2026-10-10 for "AI in B2B marketing" returned general AI sites and unrelated "case" pages (Case IH, case.edu); citations stayed valid but sources were weak.
