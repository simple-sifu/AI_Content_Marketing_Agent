"""Graph entry point (referenced by langgraph.json as content_agent.graph:graph).

START -> query_handler -+- empty -> END
                        +- research -> generate_queries -> run_searches -> synthesize
                           -> post_research_router -> content_strategist -> END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from content_agent.research import generate_queries, run_searches, synthesize
from content_agent.router import (
    post_research_router,
    query_handler,
    route_after_query_handler,
    route_after_research,
)
from content_agent.state import ContentState
from content_agent.strategist import content_strategist


def build_graph():
    builder = StateGraph(ContentState)
    builder.add_node("query_handler", query_handler)
    builder.add_node("generate_queries", generate_queries)
    builder.add_node("run_searches", run_searches)
    builder.add_node("synthesize", synthesize)
    builder.add_node("post_research_router", post_research_router)
    builder.add_node("content_strategist", content_strategist)

    builder.add_edge(START, "query_handler")
    builder.add_conditional_edges(
        "query_handler",
        route_after_query_handler,
        {"end": END, "research": "generate_queries"},
    )
    builder.add_edge("generate_queries", "run_searches")
    builder.add_edge("run_searches", "synthesize")
    builder.add_edge("synthesize", "post_research_router")
    builder.add_conditional_edges(
        "post_research_router",
        route_after_research,
        {"report": "content_strategist"},
    )
    builder.add_edge("content_strategist", END)
    return builder.compile()


graph = build_graph()
