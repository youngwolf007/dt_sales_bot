import random
import time

from tools.email_tool import EMAIL_RE, send_email

OTP_TTL_SECONDS = 5 * 60
MAX_ATTEMPTS = 5

# In-memory OTP store: email -> {"code", "expires_at", "attempts"}.
# Single-process, resets on restart — sufficient for a hackathon demo.
_otp_store: dict[str, dict] = {}


def generate_and_send_otp(email: str) -> str | None:
    """Generate a one-time code, email it to the given address.

    Returns an error message on failure, or None on success.
    """
    if not EMAIL_RE.match(email):
        return "That doesn't look like a valid email address."

    code = f"{random.randint(0, 999999):06d}"
    _otp_store[email] = {"code": code, "expires_at": time.time() + OTP_TTL_SECONDS, "attempts": 0}

    subject = "Your Deutsche Telekom Sales Bot verification code"
    text_body = f"Your verification code is {code}. It expires in 5 minutes."
    html_body = (
        f"<p>Your verification code is <strong style='font-size:20px;'>{code}</strong>.</p>"
        "<p>It expires in 5 minutes.</p>"
    )

    try:
        send_email(email, subject, text_body, html_body)
    except Exception as exc:  # noqa: BLE001 - surface SMTP failures to the caller
        del _otp_store[email]
        return f"Couldn't send the code: {exc}"

    return None


def verify_otp(email: str, code: str) -> tuple[bool, str | None]:
    """Check a submitted code against the stored OTP for that email."""
    entry = _otp_store.get(email)
    if entry is None:
        return False, "No code was requested for this email. Please request a new one."

    if time.time() > entry["expires_at"]:
        del _otp_store[email]
        return False, "This code has expired. Please request a new one."

    if entry["attempts"] >= MAX_ATTEMPTS:
        del _otp_store[email]
        return False, "Too many incorrect attempts. Please request a new code."

    if code != entry["code"]:
        entry["attempts"] += 1
        return False, "Incorrect code, please try again."

    del _otp_store[email]
    return True, None
