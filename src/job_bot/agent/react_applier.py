from langgraph.graph import END, START, StateGraph

from job_bot.adt import JobAgentContext, JobAgentState
from job_bot.agent.nodes import (
    complete_page,
    infer_application_stage,
    infer_page_type,
    open_job_page,
    should_invoke_tool,
    tool_call_node,
)
from job_bot.llm import OpenAILLMProvider


def build_agent():

    model = OpenAILLMProvider().get_model()

    state = StateGraph(JobAgentState, JobAgentContext, model=model)
    state.add_node(open_job_page, name="open_job_page")
    state.add_node(infer_page_type, name="infer_page_type")
    state.add_node(infer_application_stage, name="infer_application_stage")
    state.add_node(tool_call_node, name="tool_call_node")
    state.add_node(complete_page, name="complete_page")

    state.add_edge(START, open_job_page)
    state.add_edge(open_job_page, infer_page_type)
    state.add_edge(infer_page_type, infer_application_stage)
    state.add_edge(infer_application_stage, complete_page)
    state.add_edge(complete_page, END)

    # all the non-tool nodes can conditonally transition to the tool_call_node
    state.add_conditional_edges("open_job_page", should_invoke_tool, ["tool_call_node"])
    state.add_conditional_edges("infer_page_type", should_invoke_tool, ["tool_call_node"])
    state.add_conditional_edges("infer_application_stage", should_invoke_tool, ["tool_call_node"])
    state.add_conditional_edges("complete_page", should_invoke_tool, ["tool_call_node"])

    return state.compile()
