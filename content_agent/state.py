"""Shared graph state: the contract every agent node reads from and writes to."""

from __future__ import annotations

from typing import TypedDict


class ContentState(TypedDict, total=False):
    # Raw user request.
    request: str
    # Query Handler classification: research | blog | linkedin | image,
    # or the non-classification values "empty" (no request) and "error" (LLM failed).
    intent: str
    # Topic extracted by the Query Handler ("" when empty or on error).
    topic: str
    # Final user-facing markdown.
    final_output: str
    # Problems from the current run only. Deliberately has no reducer (no operator.add):
    # every run overwrites it, so a reused `langgraph dev` thread never carries stale errors.
    errors: list[str]
