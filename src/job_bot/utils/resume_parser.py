from functools import cache

from langchain.chat_models import BaseChatModel
from langchain.messages import HumanMessage, SystemMessage

from job_bot.llm import OpenAILLMProvider
from job_bot.schemas import User


@cache
def get_parser_model() -> BaseChatModel:
    model = OpenAILLMProvider().get_model()
    return model.with_structured_output(User)


_PARSE_PROMPT = f"""
You are a resume parser. Extract the following information from the resume:
{", ".join(User.model_fields.keys())}
The "summary" field should concisely describe the user's qualifications and
experience, highlighting key skills and achievements.
"""


def ai_parse_resume(resume: str) -> User:
    """
    Parse a resume file and extract candidate information.

    Args:
        resume (str): The resume file content as a string.

    Returns:
        User: The extracted user profile.
    """
    model = get_parser_model()
    res = model.invoke([SystemMessage(content=f"{_PARSE_PROMPT}"), HumanMessage(content=resume)])
    return res
