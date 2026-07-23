from typing import Sequence

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import BaseTool
from langgraph.runtime import Runtime

from job_bot.adt import JobAgentContext, JobAgentState, JobPageType


def should_invoke_tool(state: JobAgentState) -> bool:
    """
    Determine if the last message in the state contains a tool call.

    Args:
        state (JobAgentState): The current state of the application agent.
    Returns:

        bool: True if the last message contains a tool call, False otherwise.
    """
    if not state.messages:
        return False
    last_message = state.messages[-1]
    return isinstance(last_message, AIMessage) and bool(last_message.tool_calls)


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


def open_job_page(state: JobAgentState, runtime: Runtime[JobAgentContext]) -> JobAgentState:
    """
    Open the job URL in the browser session.

    Args:
        state (JobAgentState): The current state of the application agent.
        runtime (Runtime[JobAgentContext]): The runtime context containing the browser session.

    Returns:
        JobAgentState: The updated state after opening the job URL.
    """
    if not runtime.context.browser_session:
        raise RuntimeError("Browser session is not initialized in the state.")

    browser_session = runtime.context.browser_session
    job_url = state.job_url

    if not job_url:
        raise RuntimeError("No job URL found in the state messages.")

    browser_session.start(job_url)

    return JobAgentState(
        messages=state.messages + [AIMessage(content=f"Navigated to {job_url}")],
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
    model = runtime.context.model
    browser_tools = runtime.context.browser_tools
    if not browser_tools:
        raise RuntimeError("Browser tools are not initialized in the state.")
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


def complete_page(state: JobAgentState, runtime: Runtime[JobAgentContext]) -> JobAgentState:
    """
    Do things to complete the tasks to be done on the current page based on the application agent state.

    Args:
        state (JobAgentState): The current state of the application agent.

    Returns:
        JobAgentState: The updated state after completing the page tasks.
    """

    page_prompt_map: dict[JobPageType, str] = {
        JobPageType.JOB_DESCRIPTION: (
            "Inspect the current page and confirm that it is the intended job description."
            "Find the Apply or Apply now control associated with this job; ignore job-alert, newsletter, search, and unrelated sign-up controls."
            "Click the application control, then inspect the resulting page or newly opened tab before taking another action."
        ),
        JobPageType.ACCOUNT_LOGIN: (
            "Inspect the login form and identify its required fields and available sign-in options."
            "Use only credentials explicitly supplied in the conversation or runtime context; never invent credentials."
            "Fill the matching email, username, and password fields, submit the form, and inspect the resulting page."
            "If credentials are unavailable, a CAPTCHA or multi-factor challenge appears, or login fails, stop and clearly report the blocker.",
        ),
        JobPageType.APPLICATION_FORM: (
            "Inspect the application form, including all steps, required fields, validation messages, and relevant embedded frames."
            "Complete each field using only the supplied candidate profile; never guess or invent candidate information."
            "Upload a resume only when an explicit, valid resume file path is available, and do not agree to optional marketing communications."
            "After each logical form step, inspect the page again and correct validation errors before continuing."
            "Review all entered information, submit the application, and verify that the page shows a clear submission confirmation."
            "If required information is missing, a CAPTCHA or other human-verification challenge appears, or submission cannot be confirmed, stop and report exactly what is blocking completion.",
        ),
        JobPageType.UNKNOWN: (
            "Inspect the current page, its visible messages, interactive controls, URL, and any relevant embedded frames."
            "Determine whether the page is a loading state, confirmation page, expired posting, access error, validation error, CAPTCHA, or an unrecognized application step."
            "Take only an action that is clearly supported by the inspected page and advances the existing job application; do not click unrelated controls or enter invented data."
            "Inspect the page after the action. If no safe next action is clear, stop and report the page state and blocker.",
        ),
    }

    page_prompts = page_prompt_map.get(state.job_page_type)
    if page_prompts is None:
        raise RuntimeError(f"Unknown page type: {state.job_page_type}")
    user_prompt = HumanMessage(content=page_prompts)
    model = runtime.context.model
    resp = model.invoke(state.messages + [user_prompt])
    return JobAgentState(
        messages=[resp],
        application_stage=state.application_stage,
        job_page_type=state.job_page_type,
    )
