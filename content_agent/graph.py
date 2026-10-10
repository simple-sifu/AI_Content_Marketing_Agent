"""Graph entry point (referenced by langgraph.json as content_agent.graph:graph).

START -> query_handler --(research | blog | linkedin)--> generate_queries
                       \\--(image | empty | error)------> END

generate_queries --(ok)--> run_searches -> synthesize -> END
                 \\--(intent=error)--> END

synthesize ends on intent=error and, until the report formatter exists (entry 3),
on success too, with cited findings and a numbered source list as final_output.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from content_agent.research import generate_queries, run_searches, synthesize
from content_agent.router import query_handler, route_after_query_handler
from content_agent.state import ContentState


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

    builder.add_edge(START, "query_handler")
    builder.add_conditional_edges(
        "query_handler", route_after_query_handler, ["generate_queries", END]
    )
    builder.add_conditional_edges(
        "generate_queries", _end_on_error("run_searches"), ["run_searches", END]
    )
    builder.add_edge("run_searches", "synthesize")
    # Success and intent=error both end for now; entry 3 routes with _end_on_error here.
    builder.add_edge("synthesize", END)
    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
