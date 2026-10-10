"""Query Handler (classify + topic) and post-research router (blog, linkedin or report);
routing helpers."""

from __future__ import annotations

from typing import Literal

import openai
from langchain_core.exceptions import OutputParserException
from langchain_openai.chat_models.base import OpenAIRefusalError
from langgraph.graph import END
from pydantic import BaseModel, Field

from content_agent import llm
from content_agent.research import _LLM_ERRORS, _llm_failure
from content_agent.state import ContentState

NODE_NAME = "query_handler"
RESEARCH_INTENTS = frozenset({"research", "blog", "linkedin"})

EMPTY_REQUEST_MESSAGE = (
    "Please tell me what topic you would like content about, for example: "
    '"Research AI trends in B2B marketing".'
)

QUERY_HANDLER_PROMPT = """You are the query handler of a content marketing agent.
Classify the user's request and extract the core topic.

Intents:
- research: the user wants research, a report, an overview or analysis of a topic.
- blog: the user wants a blog post or article.
- linkedin: the user wants a LinkedIn post.
- image: the user wants an image, graphic or visual.

The topic is a concise noun phrase describing the subject matter (no instructions,
no format words like "blog post" or "LinkedIn").

User request:
{request}
"""

# Image fields are written only on image runs; every run starts by clearing them so a reused
# `langgraph dev` thread never shows an earlier run's image.
_IMAGE_RESET = {"image_prompt": "", "image_path": "", "image_model": ""}


class RouteDecision(BaseModel):
    # "empty" and "error" are set by the node itself and deliberately absent here:
    # the LLM must never choose them.
    intent: Literal["research", "blog", "linkedin", "image"] = Field(
        description="What kind of content the user is asking for."
    )
    topic: str = Field(description="The subject matter of the request.")


def query_handler(state: ContentState) -> dict:
    """Every return writes intent, topic, errors and clears the image fields so a reused thread only ever shows this
    run's result; empty and error runs end here and also write final_output. Classified runs
    continue to a node that writes final_output."""
    request = (state.get("request") or "").strip()
    if not request:
        return {
            **_IMAGE_RESET,
            "intent": "empty",
            "topic": "",
            "final_output": EMPTY_REQUEST_MESSAGE,
            "errors": [],
        }

    try:
        # get_llm() is inside the try: a missing key raises OpenAIError at construction.
        structured = llm.get_llm(temperature=0).with_structured_output(RouteDecision)
        decision = structured.invoke(QUERY_HANDLER_PROMPT.format(request=request))
        if not isinstance(decision, RouteDecision):
            raise OutputParserException("structured output did not match RouteDecision")
    # ValueError covers OutputParserException and pydantic.ValidationError from parsing.
    except (openai.OpenAIError, ValueError, OpenAIRefusalError) as exc:
        message = llm.llm_error(NODE_NAME, exc)
        return {
            **_IMAGE_RESET,
            "intent": "error",
            "topic": "",
            "final_output": message,
            "errors": [f"{NODE_NAME}: {type(exc).__name__}"],
        }

    return {
        **_IMAGE_RESET,
        "intent": decision.intent,
        "topic": decision.topic.strip() or request,
        "errors": [],
    }


def route_after_query_handler(state: ContentState) -> str:
    """Research, blog and LinkedIn requests go to Deep Research, image requests to the Image
    Generator; empty and error runs end."""
    intent = state.get("intent")
    if intent in RESEARCH_INTENTS:
        return "generate_queries"
    return "image_generator" if intent == "image" else END


# --- Post-research router -------------------------------------------------------------

POST_RESEARCH_NODE = "post_research_router"

POST_RESEARCH_PROMPT = """You are the editor of a content marketing agent. Research on the
user's topic is done. Decide which format to write from it.

Formats:
- blog: the user asked for a blog post or article.
- linkedin: the user asked for a LinkedIn post.
- report: anything else (a research report, overview or analysis, or an unclear request).

User request:
{request}

Classified intent: {intent}
"""


_WRITER_NODES = {"blog": "blog_writer", "linkedin": "linkedin_writer"}


class PostResearchDecision(BaseModel):
    target_format: Literal["blog", "linkedin", "report"] = Field(
        description="Which format to write from the research."
    )


def post_research_router(state: ContentState) -> dict:
    """Pick blog, linkedin or report. Runs only when research found sources; always writes target_format."""
    prompt = POST_RESEARCH_PROMPT.format(
        request=(state.get("request") or "").strip(), intent=state.get("intent") or ""
    )
    try:
        structured = llm.get_llm(temperature=0).with_structured_output(PostResearchDecision)
        decision = structured.invoke(prompt)
        if not isinstance(decision, PostResearchDecision):
            raise OutputParserException("structured output did not match PostResearchDecision")
    except _LLM_ERRORS as exc:
        return {"target_format": "", **_llm_failure(state, POST_RESEARCH_NODE, exc)}
    return {"target_format": decision.target_format}


def route_after_research(state: ContentState) -> str:
    """After the post-research router: blog or LinkedIn writer, strategist report, or END on error."""
    if state.get("intent") == "error":
        return END
    return _WRITER_NODES.get(state.get("target_format") or "", "content_strategist")
