from functools import cache

from langchain.chat_models import BaseChatModel
from langchain.messages import HumanMessage, SystemMessage

from job_bot.flow import CandidateProfile
from job_bot.llm import OpenAILLMProvider


@cache
def get_parser_model() -> BaseChatModel:
    model = OpenAILLMProvider().get_model()
    return model.with_structured_output(CandidateProfile)


_PARSE_PROMPT = f"""
You are a resume parser. Extract the following information from the resume:
{", ".join(CandidateProfile.model_fields.keys())}
The "summary" field should be a concise summary of the candidate's qualifications and experience, highlighting their key skills and achievements.
"""


def parse_resume(resume: str) -> CandidateProfile:
    """
    Parse a resume file and extract candidate information.

    Args:
        resume (str): The resume file content as a string.

    Returns:
        CandidateProfile: The extracted candidate profile.
    """
    model = get_parser_model()
    res = model.invoke([SystemMessage(content=f"{_PARSE_PROMPT}"), HumanMessage(content=resume)])
    return res
