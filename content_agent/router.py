"""Query Handler (pre-research router) and post-research router."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from content_agent import llm
from content_agent.state import ContentState

EMPTY_REQUEST_MESSAGE = (
    "Please tell me what topic you would like researched, for example: "
    '"Research AI trends in B2B marketing".'
)

QUERY_HANDLER_PROMPT = """You are the query handler of a content marketing agent.
Classify the user's request and extract the core topic to research.

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


class RouteDecision(BaseModel):
    intent: Literal["research", "blog", "linkedin", "image"] = Field(
        description="What kind of content the user is asking for."
    )
    topic: str = Field(description="The subject matter to research.")


def query_handler(state: ContentState) -> dict:
    request = (state.get("request") or "").strip()
    if not request:
        return {"intent": "empty", "final_output": EMPTY_REQUEST_MESSAGE}

    structured = llm.get_llm(temperature=0).with_structured_output(RouteDecision)
    decision: RouteDecision = structured.invoke(QUERY_HANDLER_PROMPT.format(request=request))
    topic = decision.topic.strip() or request
    return {"intent": decision.intent, "topic": topic}


def route_after_query_handler(state: ContentState) -> str:
    """Conditional edge: short-circuit empty requests, otherwise start research."""
    return "end" if state.get("intent") == "empty" else "research"


# Formats with a wired output node. Blog/LinkedIn/image writers are deferred.
WIRED_FORMATS = {"report"}


def post_research_router(state: ContentState) -> dict:
    """Pick the output format. Only the markdown research report is wired today;
    deferred formats fall back to it and the strategist adds a note."""
    return {"target_format": "report"}


def route_after_research(state: ContentState) -> str:
    target = state.get("target_format", "report")
    return target if target in WIRED_FORMATS else "report"
