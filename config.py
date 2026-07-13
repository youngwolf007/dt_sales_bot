import os

from dotenv import load_dotenv

load_dotenv(override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-4.1")

# Optional: enables automatic fallback to Gemini when OpenAI rate-limits.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite")

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

_REQUIRED = {
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "EMAIL_ADDRESS": EMAIL_ADDRESS,
    "EMAIL_SMTP_SERVER": EMAIL_SMTP_SERVER,
    "EMAIL_APP_PASSWORD": EMAIL_APP_PASSWORD,
}
_missing = [name for name, value in _REQUIRED.items() if not value]
if _missing:
    raise RuntimeError(
        "Missing required environment variable(s): "
        f"{', '.join(_missing)}. Copy .env.example to .env and fill them in."
    )
