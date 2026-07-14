"""Storage-agnostic lead store interface, so the Google Sheets backend can
later be swapped for a real CRM (Salesforce, HubSpot, etc.) without touching
the agent tools in tools/crm_tool.py. Implementations work on plain dicts
keyed by the Lead model's field names, keeping this layer decoupled from
the bot's pydantic schema.
"""

import logging
import time
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)


class LeadStore(Protocol):
    def search(self, email: str | None, company: str | None) -> list[dict]: ...

    def create(self, lead: dict) -> dict: ...

    def update(self, email: str | None, updates: dict) -> dict | None: ...

    def upsert(self, lead: dict) -> tuple[dict, bool]:
        """Returns (lead_dict, was_created)."""
        ...


def call_with_retry(
    func: Callable,
    *args,
    retry_on: tuple[type[BaseException], ...],
    max_attempts: int = 3,
    base_delay: float = 0.5,
    is_retryable: Callable[[BaseException], bool] | None = None,
    **kwargs,
):
    """Call func(*args, **kwargs), retrying on exceptions matching retry_on
    (and, if is_retryable is given, only those that also pass that predicate
    — used to distinguish a transient 429/5xx from a non-retryable 4xx) with
    exponential backoff. Re-raises the last exception once max_attempts is
    exhausted or on a non-retryable error."""
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except retry_on as exc:
            if is_retryable is not None and not is_retryable(exc):
                raise
            last_exc = exc
            logger.warning("Transient CRM store error (attempt %d/%d): %s", attempt + 1, max_attempts, exc)
            if attempt < max_attempts - 1:
                time.sleep(base_delay * (2**attempt))
    assert last_exc is not None
    raise last_exc
