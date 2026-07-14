import os
from pathlib import Path

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

# Optional: Google Sheets CRM. If unset, the CRM tools return a clear error
# instead of the app failing to start.
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SHEETS_WORKSHEET_NAME = os.getenv("GOOGLE_SHEETS_WORKSHEET_NAME", "Leads")

# Hosts like HF Spaces have no file upload for secrets, only env vars: paste the
# service account JSON into GOOGLE_SERVICE_ACCOUNT_JSON and it's materialized here.
_GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
if _GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_APPLICATION_CREDENTIALS:
    _cred_path = Path(GOOGLE_APPLICATION_CREDENTIALS)
    if not _cred_path.exists():
        _cred_path.parent.mkdir(parents=True, exist_ok=True)
        _cred_path.write_text(_GOOGLE_SERVICE_ACCOUNT_JSON)

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
