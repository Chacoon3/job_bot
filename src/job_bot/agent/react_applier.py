from langgraph.graph import StateGraph

from job_bot.adt import JobAgentContext, JobAgentState
from job_bot.agent.nodes import infer_application_stage, infer_page_type, tool_call_node
from job_bot.llm import OpenAILLMProvider


def build_agent():

    model = OpenAILLMProvider().get_model()

    state = StateGraph(JobAgentState, JobAgentContext, model=model)
    state.add_node(infer_page_type, name="infer_page_type")
    state.add_node(infer_application_stage, name="infer_application_stage")
    state.add_node(tool_call_node, name="tool_call_node")

    return state.compile()
