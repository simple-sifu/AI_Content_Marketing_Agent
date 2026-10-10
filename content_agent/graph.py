"""Graph entry point (referenced by langgraph.json as content_agent.graph:graph).

START -> query_handler --(research | blog | linkedin)--> generate_queries
                       \\--(image | empty | error)------> END

generate_queries --(ok)--> run_searches -> synthesize
                 \\--(intent=error)--> END

synthesize --(ok, sources)----> post_research_router --(blog)------> blog_writer -> END
           |                                        |--(linkedin)--> linkedin_writer -> END
           |                                        |--(report)----> content_strategist -> END
           |                                        \\--(intent=error)--> END
           |--(ok, no sources)--> content_strategist -> END
           \\--(intent=error)----> END

post_research_router picks blog, linkedin or report. blog_writer writes the SEO blog post,
linkedin_writer the LinkedIn post, content_strategist the markdown research report, each as
final_output. A run with no sources never gets a blog or LinkedIn post: it goes straight to
the strategist's no-sources report.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from content_agent.blog import blog_writer
from content_agent.linkedin import linkedin_writer
from content_agent.research import generate_queries, run_searches, synthesize
from content_agent.router import (
    post_research_router,
    query_handler,
    route_after_query_handler,
    route_after_research,
)
from content_agent.state import ContentState
from content_agent.strategist import content_strategist


def _end_on_error(next_node: str):
    def route(state: ContentState) -> str:
        return END if state.get("intent") == "error" else next_node

    return route


def _route_after_synthesize(state: ContentState) -> str:
    if state.get("intent") == "error":
        return END
    return "post_research_router" if state.get("sources") else "content_strategist"


def build_graph(checkpointer=None):
    builder = StateGraph(ContentState)
    builder.add_node("query_handler", query_handler)
    builder.add_node("generate_queries", generate_queries)
    builder.add_node("run_searches", run_searches)
    builder.add_node("synthesize", synthesize)
    builder.add_node("post_research_router", post_research_router)
    builder.add_node("blog_writer", blog_writer)
    builder.add_node("linkedin_writer", linkedin_writer)
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
        "synthesize",
        _route_after_synthesize,
        ["post_research_router", "content_strategist", END],
    )
    builder.add_conditional_edges(
        "post_research_router",
        route_after_research,
        ["blog_writer", "linkedin_writer", "content_strategist", END],
    )
    # The writers' last step either way (an LLM failure sets intent=error and ends too).
    builder.add_edge("blog_writer", END)
    builder.add_edge("linkedin_writer", END)
    builder.add_edge("content_strategist", END)
    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
