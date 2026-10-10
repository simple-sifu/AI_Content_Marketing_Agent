"""Single switch point for the chat model used by every node."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# Loads .env for plain `python`/pytest runs; `langgraph dev` also injects it via langgraph.json.
load_dotenv()

DEFAULT_MODEL = "gpt-4o-mini"


def get_llm(temperature: float = 0.2) -> ChatOpenAI:
    """Return the configured chat model. Constructed lazily so imports never need a key."""
    model = os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
    return ChatOpenAI(model=model, temperature=temperature)
