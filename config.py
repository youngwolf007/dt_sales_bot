import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)


def _clean_env(name: str, default: str | None = None) -> str | None:
    """os.getenv, stripped of surrounding whitespace and stray BOM characters
    (﻿) that some editors/hosting secret UIs sneak into pasted values —
    those aren't whitespace, so plain .strip() won't catch them, and they
    blow up smtplib's user.encode("ascii") in login() with a cryptic error."""
    value = os.getenv(name, default)
    return value.replace("﻿", "").strip() if value else value


OPENAI_API_KEY = _clean_env("OPENAI_API_KEY")
DEFAULT_MODEL_NAME = _clean_env("DEFAULT_MODEL_NAME", "gpt-4.1")

# Optional: enables automatic fallback to Gemini when OpenAI rate-limits.
GEMINI_API_KEY = _clean_env("GEMINI_API_KEY")
GEMINI_MODEL_NAME = _clean_env("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite")

EMAIL_ADDRESS = _clean_env("EMAIL_ADDRESS")
EMAIL_SMTP_SERVER = _clean_env("EMAIL_SMTP_SERVER")
EMAIL_APP_PASSWORD = _clean_env("EMAIL_APP_PASSWORD")

# Optional: Pushover push notification on each login. If unset, notifications
# are silently skipped instead of the app failing to start.
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN")
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY")

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
