"""Pure matching/merge helpers for lead lookups, with no gspread or network
dependency, so this logic can be unit-verified without live credentials.

Search priority when more than one identifier is available is email >
company: email is an exact identity lookup, while company is a fuzzy
substring match that can return multiple leads, so it's only used as a
fallback rather than OR-ed together with the precise identifier.
"""

import re
from datetime import datetime, timezone


def emails_match(a: str | None, b: str | None) -> bool:
    """Case-insensitive exact match."""
    return bool(a) and bool(b) and a.strip().lower() == b.strip().lower()


def company_matches(query: str | None, candidate: str | None) -> bool:
    """Case-insensitive substring match, checked in either direction, for
    partial company-name search (e.g. 'Acme' matches 'Acme Corp GmbH')."""
    if not query or not candidate:
        return False
    q, c = query.strip().lower(), candidate.strip().lower()
    return q in c or c in q


def merge_products(existing: str | None, new_items: str | None) -> str:
    """Merge a comma/semicolon-separated 'existing' string with 'new_items',
    de-duplicating case-insensitively while preserving original casing and
    order of first occurrence. New items are appended after existing ones."""
    seen: dict[str, str] = {}
    for raw in re.split(r"[,;]\s*", (existing or "").strip()):
        item = raw.strip()
        if item and item.lower() not in seen:
            seen[item.lower()] = item
    for raw in re.split(r"[,;]\s*", (new_items or "").strip()):
        item = raw.strip()
        if item and item.lower() not in seen:
            seen[item.lower()] = item
    return ", ".join(seen.values())


def append_note(existing: str | None, new_note: str | None, timestamp: datetime | None = None) -> str:
    """Append new_note as a new timestamped line to existing notes, preserving
    all prior lines. Never truncates prior content."""
    if not new_note or not new_note.strip():
        return existing or ""
    ts = timestamp or datetime.now(timezone.utc)
    line = f"[{ts.strftime('%Y-%m-%d %H:%M UTC')}] {new_note.strip()}"
    existing = (existing or "").strip()
    return f"{existing}\n{line}" if existing else line
