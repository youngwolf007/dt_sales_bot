import requests

from config import PUSHOVER_API_TOKEN, PUSHOVER_USER_KEY

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"


def send_push_notification(title: str, message: str) -> None:
    """Send a Pushover push notification. No-ops if Pushover isn't configured."""
    if not PUSHOVER_API_TOKEN or not PUSHOVER_USER_KEY:
        return

    requests.post(
        PUSHOVER_API_URL,
        data={
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": message,
        },
        timeout=10,
    ).raise_for_status()
