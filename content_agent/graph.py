"""Graph entry point (referenced by langgraph.json as content_agent.graph:graph).

START -> query_handler -> END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from content_agent.router import query_handler
from content_agent.state import ContentState


def build_graph(checkpointer=None):
    builder = StateGraph(ContentState)
    builder.add_node("query_handler", query_handler)
    builder.add_edge(START, "query_handler")
    builder.add_edge("query_handler", END)
    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
