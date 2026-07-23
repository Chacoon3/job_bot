from typing import Sequence

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import BaseTool
from langgraph.runtime import Runtime

from job_bot.adt import JobAgentContext, JobAgentState, JobPageType
from job_bot.llm import OpenAILLMProvider


def init_browser_session(state: JobAgentState, runtime: Runtime[JobAgentContext]) -> JobAgentState:
    """
    Initialize a browser session for the application agent.

    Args:
        state (JobAgentState): The current state of the application agent.
        runtime (Runtime[JobAgentContext]): The runtime context containing the browser session.

    Returns:
        JobAgentState: The updated state with the initialized browser session.
    """
    if runtime.context.browser_session is None:
        raise RuntimeError("Browser session is not initialized in the runtime context.")

    return JobAgentState(
        messages=[],
        application_stage=state.application_stage,
        job_page_type=state.job_page_type,
    )


def tool_call_node(state: JobAgentState, tools: Sequence[BaseTool]) -> JobAgentState:
    registry: dict[str, BaseTool] = {tool.name: tool for tool in tools}
    tool_msgs = []
    for tool_call in state.messages[-1].tool_calls:
        tool = registry.get(tool_call["name"])
        if tool is None:
            raise ValueError(f"Tool call '{tool_call['name']}' is not supported")
        observation = tool.invoke(tool_call["args"])
        tool_msgs.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))

    return JobAgentState(
        messages=tool_msgs,
        application_stage=state.application_stage,
        job_page_type=state.job_page_type,
    )


def infer_page_type(state: JobAgentState, runtime: Runtime[JobAgentContext]) -> JobAgentState:
    """
    Infer the current page type based on the application agent state.

    Args:
        state (JobAgentState): The current state of the application agent.

    Returns:
        JobAgentState: The updated state with the inferred page type.
    """
    model = OpenAILLMProvider(parallel_tool_calls=False).get_model()
    browser_tools = runtime.context.browser_tools
    if not browser_tools:
        raise RuntimeError("Browser tools are not initialized in the state.")
    model.bind_tools(browser_tools)
    structured = model.with_structured_output(JobPageType)

    prompts = [
        SystemMessage("""
You are an assistant for automated job application.
You should use the available tools you have to inspect the current web page and determine the type of page you are on.
The possible page types are:
1. Job Description Page: This page contains the job description and details about the position. It may have an "Apply" button or link to proceed with the application.
2. Account Login Page: This page requires the user to log in to their account before proceeding with the application. It may have fields for username/email and password, and a "Login" button.
3. Application Form Page: This page contains the actual application form that needs to be filled out with the candidate's information. It may have various input fields, checkboxes, and a "Submit" button to complete the application process.
4. Unknown Page Type: If the page does not match any of the above types, classify it as "Unknown".
You should analyze the messages in the state to determine the current page type.
Note that if a page meets the criteria for multiple page types, you should prioritize the classification in the following order:
1. Application Form Page
2. Account Login Page
3. Job Description Page
If the page does not meet the criteria for any of the above types, classify it as "Unknown".
            """),
        HumanMessage(content="Infer the current page type based on the web page content. "),
    ]

    page_type: JobPageType = structured.invoke(prompts)

    state.job_page_type = page_type
    return JobAgentState(
        messages=state.messages + [AIMessage(content=page_type.name)],
        application_stage=state.application_stage,
        job_page_type=page_type,
    )


def infer_application_stage(
    state: JobAgentState, runtime: Runtime[JobAgentContext]
) -> JobAgentState:
    """
    Infer the current application stage based on the application agent state.

    Args:
        state (JobAgentState): The current state of the application agent.

    Returns:
        JobAgentState: The updated state with the inferred application stage.
    """
    try:
        page_type = JobPageType(state.messages[-1].content)
    except Exception:
        raise RuntimeError(
            f"The last message in the state does not contain a valid page type. Received: {state.messages[-1].content}"
        )

    expected_stage = page_type.to_application_stage()
    if state.application_stage != expected_stage:
        if state.application_stage.can_transition_to(expected_stage):
            state.application_stage = expected_stage
        else:
            raise RuntimeError(
                f"Invalid transition from {state.application_stage} to {expected_stage} based on page type {page_type}."
            )

    return JobAgentState(
        messages=[],
        application_stage=state.application_stage,
        job_page_type=page_type,
    )


def _start_application(state: JobAgentState, runtime: Runtime[JobAgentContext]) -> JobAgentState:
    """
    Start the application process based on the application agent state.

    Args:
        state (JobAgentState): The current state of the application agent.

    """
    # Implement application starting logic here
    return state


def _login(state: JobAgentState, runtime: Runtime[JobAgentContext]) -> JobAgentState:
    """
    Perform login actions based on the application agent state.

    Args:
        state (JobAgentState): The current state of the application agent.

    """
    # Implement login logic here
    return state


def _fill_application_page(
    state: JobAgentState, runtime: Runtime[JobAgentContext]
) -> JobAgentState:
    """
    Fill out the application form based on the application agent state.

    Args:
        state (JobAgentState): The current state of the application agent.

    """
    # Implement application form filling logic here
    return state


def _check_application_error(
    state: JobAgentState, runtime: Runtime[JobAgentContext]
) -> JobAgentState:
    """
    Check for any errors in the application submission based on the application agent state.

    Args:
        state (JobAgentState): The current state of the application agent.

    """
    # Implement error checking logic here
    return state


def complete_page(state: JobAgentState, runtime: Runtime[JobAgentContext]) -> JobAgentState:
    """
    Do things to complete the tasks to be done on the current page based on the application agent state.

    Args:
        state (JobAgentState): The current state of the application agent.

    """

    page_prompt_map = {
        JobPageType.JOB_DESCRIPTION: "You are on a job description page. Your task is to find the relevant Apply/Apply now control in the interactive snapshot and click it.",
        JobPageType.ACCOUNT_LOGIN: "You are on an account login page. Your task is to fill in the login credentials and submit the form.",
        JobPageType.APPLICATION_FORM: "You are on an application form page. Your task is to fill out the application form with the candidate's information and submit it.",
        JobPageType.UNKNOWN: "You are on an unknown page type. Your task is to check for any errors or issues that may have occurred during the application process.",
    }

    user_prompt = page_prompt_map.get(state.job_page_type)
    if user_prompt is None:
        raise RuntimeError(f"Unknown page type: {state.job_page_type}")

    if runtime.context.model is None:
        model = OpenAILLMProvider(parallel_tool_calls=False).get_model()
