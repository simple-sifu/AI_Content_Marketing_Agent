"""Query Handler: classifies the request and extracts its topic."""

from __future__ import annotations

from typing import Literal

import openai
from langchain_core.exceptions import OutputParserException
from langchain_openai.chat_models.base import OpenAIRefusalError
from pydantic import BaseModel, Field

from content_agent import llm
from content_agent.state import ContentState

NODE_NAME = "query_handler"

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

SUCCESS_TEMPLATE = (
    "**Intent:** {intent}\n"
    "**Topic:** {topic}\n"
    "\n"
    "The {writer} is not built yet; this run stops after classification."
)

_WRITERS = {
    "research": "research agent",
    "blog": "blog writer",
    "linkedin": "LinkedIn writer",
    "image": "image generator",
}


class RouteDecision(BaseModel):
    # "empty" and "error" are set by the node itself and deliberately absent here:
    # the LLM must never choose them.
    intent: Literal["research", "blog", "linkedin", "image"] = Field(
        description="What kind of content the user is asking for."
    )
    topic: str = Field(description="The subject matter of the request.")


def query_handler(state: ContentState) -> dict:
    """Every return writes intent, topic, final_output and errors so a reused thread
    only ever shows this run's result."""
    request = (state.get("request") or "").strip()
    if not request:
        return {
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
            "intent": "error",
            "topic": "",
            "final_output": message,
            "errors": [f"{NODE_NAME}: {type(exc).__name__}"],
        }

    topic = decision.topic.strip() or request
    return {
        "intent": decision.intent,
        "topic": topic,
        "final_output": SUCCESS_TEMPLATE.format(
            intent=decision.intent, topic=topic, writer=_WRITERS[decision.intent]
        ),
        "errors": [],
    }
