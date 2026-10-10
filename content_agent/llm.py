"""Single switch point for the chat model, plus the LLM error convention every node follows."""

from __future__ import annotations

import os

import openai
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import OpenAIRefusalError

# Loads .env for plain `python`/pytest runs; `langgraph dev` also injects it via langgraph.json.
load_dotenv()

DEFAULT_MODEL = "gpt-4o-mini"


def get_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Return the configured chat model. Constructed lazily so imports never need a key."""
    model = os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
    return ChatOpenAI(model=model, temperature=temperature)


def llm_error(node: str, exc: Exception) -> str:
    """Readable, key-free message for an LLM failure in `node`.

    Only the exception class name is used, never its text: OpenAI error messages and
    responses can echo request details, so they must not reach the user or the state.
    """
    kind = type(exc).__name__
    label = node.replace("_", " ")
    # ValueError covers OutputParserException and pydantic.ValidationError.
    if isinstance(exc, (ValueError, OpenAIRefusalError)):
        return (
            f"The {label} could not understand the model's response ({kind}). "
            "Please try again or rephrase your request."
        )
    # Exact OpenAIError is what the client raises when no API key is configured.
    if isinstance(exc, openai.AuthenticationError) or type(exc) is openai.OpenAIError:
        return (
            f"The {label} could not reach OpenAI ({kind}). "
            "Check OPENAI_API_KEY and try again."
        )
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return (
            f"The {label} could not reach OpenAI ({kind}). "
            "Check your connection and try again."
        )
    return f"OpenAI returned an error ({kind}). Please try again shortly."
