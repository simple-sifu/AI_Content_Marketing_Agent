"""Graph entry point (referenced by langgraph.json as content_agent.graph:graph).

START -> query_handler --(research | blog | linkedin)--> generate_queries
                       \\--(image | empty | error)------> END

generate_queries --(ok)--> run_searches -> synthesize --(ok)--> content_strategist -> END
                 \\--(intent=error)--> END              \\--(intent=error)--> END

content_strategist writes the markdown research report as final_output. It is also
the ending for blog and LinkedIn requests until their writers exist (entries 4-5).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from content_agent.research import generate_queries, run_searches, synthesize
from content_agent.router import query_handler, route_after_query_handler
from content_agent.state import ContentState
from content_agent.strategist import content_strategist


def _end_on_error(next_node: str):
    def route(state: ContentState) -> str:
        return END if state.get("intent") == "error" else next_node

    return route


def build_graph(checkpointer=None):
    builder = StateGraph(ContentState)
    builder.add_node("query_handler", query_handler)
    builder.add_node("generate_queries", generate_queries)
    builder.add_node("run_searches", run_searches)
    builder.add_node("synthesize", synthesize)
    builder.add_node("content_strategist", content_strategist)

    builder.add_edge(START, "query_handler")
    builder.add_conditional_edges(
        "query_handler", route_after_query_handler, ["generate_queries", END]
    )
    builder.add_conditional_edges(
        "generate_queries", _end_on_error("run_searches"), ["run_searches", END]
    )
    builder.add_edge("run_searches", "synthesize")
    builder.add_conditional_edges(
        "synthesize", _end_on_error("content_strategist"), ["content_strategist", END]
    )
    builder.add_edge("content_strategist", END)
    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
