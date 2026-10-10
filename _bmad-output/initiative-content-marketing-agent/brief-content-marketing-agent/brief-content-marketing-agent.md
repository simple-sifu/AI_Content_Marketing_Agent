# Content Marketing Agent — project brief (verbatim from the user, 2026-10-10)

## Customer Problem

Solo creators and small marketing teams have to produce content accross formats - blog posts, Linkedin posts, social images - every week to stay visible. Each format has different rules: SEO keyword density for blogs, 1300-character hooks for Linkedin, prompt craft for images, Quality research takes hours per piece. Big companies have dedicated content teams and design departments; everyone else either burns out or publishes mediocre output that doesnt convert.

## Proposed Solution

A multi-agent content factory where each agent specializes in one content type, coordinated by a smart LLM-based router. Six agents:
- Query Handler - routes the request (research? blog? Linkedin? image?)
- Deep Research Agent - generates multiple strategic search queries, synthesizes findings with source citations
- SEO Blog Writer - produces long-form content with keyword density, meta description, H1/H2/H3 structure
- Linkedin Writer - 1300-1600 char posts with hook, story, CTA, and 8-12 hashtags.
- Image Generator - enhances user prompts, generated via DALL-E with fallback chain (gpt-image-1 -> DALL-E 3 -> DALL-E 2)
- Content Strategist - formats research into readable reports when no specific format was requested.

The router does both initial routing (what does the user want?) and post-research routing (now that we'vs researched, are we writing a blog, a Linkedin post or just a research summary?). Built on LangGraph with langgraph dev for local iteration and LangGraph Cloud-ready deployment.

## Tech Stack

LangGraph, LangChain, OpenAI GPT-4 Turbo, DALL-E for image generation, SerpAPI for web research, Pillow + Matplotlib for image handling.

## External APIs & Services Required

| Service | Purpose | Notes |
|---|---|---|
| OpenAI API | LLM + DALL-E image generation | Provided by the program |
| SerpAPI | Web research | Free: 100 searches/month |

Heads up: The newer gpt-image-1 model requires a verified Open AI organization. Confirm whether the program's shared OpenAI keys have org verification - if not, the fallback chain to DALL-E 3 -> DALL-E 2 will be the default path. Either works for the project requirements.

Difficulty: Medium
Single-file reference implementation provided. Good fit for students interested in content creation, prompt engineering, and multi-modal AI (text+images)
