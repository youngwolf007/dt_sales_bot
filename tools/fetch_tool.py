import ipaddress
import socket
from urllib.parse import urlparse

import requests
from agents import function_tool
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
}
MAX_CHARS = 3_000
TIMEOUT_SECONDS = 15


def _is_safe_url(url: str) -> tuple[bool, str | None]:
    """Basic SSRF guard: this tool can now fetch *any* URL the researcher finds
    (not just DT/Vonage domains — see trusted_domains.py for the separate,
    unrelated check on links actually shown to the customer), so make sure it
    can't be pointed at internal/private network addresses."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "invalid URL"
    if parsed.scheme not in ("http", "https"):
        return False, "only http/https URLs are allowed"
    host = parsed.hostname
    if not host:
        return False, "URL has no host"

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "could not resolve host"

    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False, "host resolves to a private/internal address"

    return True, None


@function_tool
def fetch_page(url: str) -> str:
    """
    Fetch any web page and return its title and readable text content.

    Use this freely to understand the customer's business in more detail —
    e.g. their own company website, an industry page, a comparison article,
    or a DT/Vonage page you found via search — whatever helps you understand
    the need better. This is for your own research context; it does NOT mean
    a page is an acceptable source_url for a solution (see your instructions
    on that). Also useful as a fallback if web search itself errors out.

    Args:
        url: The full URL of the page to fetch.
    """
    safe, reason = _is_safe_url(url)
    if not safe:
        return f"Could not fetch {url}: {reason}."

    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        return f"Could not fetch {url}: {exc}"

    soup = BeautifulSoup(response.content, "html.parser")
    title = soup.title.string if soup.title else "No title found"
    if soup.body:
        for irrelevant in soup.body(["script", "style", "img", "input", "nav", "footer"]):
            irrelevant.decompose()
        text = soup.body.get_text(separator="\n", strip=True)
    else:
        text = ""

    return f"{title}\n\n{text}"[:MAX_CHARS]
