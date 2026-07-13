"""Optional Gemini fallback model, used when OpenAI rate-limits.

Pattern verified against agents/2_openai/3_lab3.ipynb and
agents/6_mcp/backend/traders.py: Gemini's OpenAI-compatible endpoint plugged
into the Agents SDK via OpenAIChatCompletionsModel.
"""

from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from config import GEMINI_API_KEY, GEMINI_MODEL_NAME

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

_gemini_model: OpenAIChatCompletionsModel | None = None
_resolved = False


def get_gemini_model() -> OpenAIChatCompletionsModel | None:
    """Returns a cached Gemini-backed model, or None if GEMINI_API_KEY isn't set."""
    global _gemini_model, _resolved
    if not _resolved:
        if GEMINI_API_KEY:
            client = AsyncOpenAI(base_url=GEMINI_BASE_URL, api_key=GEMINI_API_KEY)
            _gemini_model = OpenAIChatCompletionsModel(model=GEMINI_MODEL_NAME, openai_client=client)
        _resolved = True
    return _gemini_model
