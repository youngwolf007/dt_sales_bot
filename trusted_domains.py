from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from models import DTSolution

TRUSTED_DOMAINS = {
    "telekom.com",
    "telekom.de",
    "t-systems.com",
    "vonage.com",
    "t-mobile.com",
}


def is_trusted_url(url: str | None) -> bool:
    """True if url is an http(s) link on an official DT-family domain (or a subdomain of one)."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False

    host = (parsed.netloc or "").lower().split("@")[-1].split(":")[0]
    return any(host == domain or host.endswith(f".{domain}") for domain in TRUSTED_DOMAINS)


def sanitize_solutions(solutions: "list[DTSolution]") -> "list[DTSolution]":
    """Defense in depth, shared by every place that shows solutions to the
    customer (research findings text, proposal email, brochure PDF): null out
    any source_url that isn't a genuine DT/Vonage domain rather than trusting
    it was carried over correctly from an earlier, already-checked step."""
    return [
        solution.model_copy(
            update={"source_url": solution.source_url if is_trusted_url(solution.source_url) else None}
        )
        for solution in solutions
    ]
