import json
import logging

from agents import RunContextWrapper, function_tool

from context import SalesContext
from crm.sheets_store import CRMNotConfiguredError, LeadAlreadyExistsError, get_lead_store
from models import Lead, LeadUpdate

logger = logging.getLogger(__name__)


def _error_response(message: str) -> str:
    logger.warning("CRM tool error: %s", message)
    return json.dumps({"error": message})


@function_tool
def search_lead(
    ctx: RunContextWrapper[SalesContext],
    email: str | None = None,
    company: str | None = None,
) -> str:
    """
    Look up one or more leads in the CRM by email or company name. Call this
    early in a conversation to check whether this customer (or a company they
    mention) already exists in the CRM, so you can personalize the
    conversation using prior notes and interests instead of starting cold —
    do this quietly in the background, don't narrate the lookup to the customer.

    If you don't pass email or company, this defaults to searching by the
    current customer's verified login email. Only pass company explicitly
    when the customer gave you a company name instead of an email, or you
    need to look up a different company they mentioned.

    Args:
        email: Exact email to search for (case-insensitive). Defaults to the
            current customer's verified email if no argument is given at all.
        company: Company name to search for (partial/substring match; may
            return multiple leads).
    """
    if email is None and company is None:
        email = ctx.context.customer_email
    try:
        leads = get_lead_store().search(email=email, company=company)
    except CRMNotConfiguredError as exc:
        return _error_response(f"CRM is not configured yet — {exc}")
    except Exception as exc:  # noqa: BLE001 - surface lookup failures to the sales agent
        return _error_response(f"Lead search failed: {exc}")

    return json.dumps({"found": bool(leads), "leads": leads})


@function_tool
def create_lead(ctx: RunContextWrapper[SalesContext], lead: Lead) -> str:
    """
    Create a brand-new lead record in the CRM. Only call this when you're
    sure the lead does NOT already exist (e.g. search_lead just returned no
    match) — otherwise prefer upsert_lead, which handles both cases safely.

    Args:
        lead: The lead's details. Use the customer's verified email/name/
            company for the current customer rather than asking them again.
    """
    try:
        created = get_lead_store().create(lead.model_dump())
    except CRMNotConfiguredError as exc:
        return _error_response(f"CRM is not configured yet — {exc}")
    except LeadAlreadyExistsError as exc:
        return json.dumps({"created": False, "reason": "already_exists", "lead": exc.existing})
    except Exception as exc:  # noqa: BLE001 - surface creation failures to the sales agent
        return _error_response(f"Lead creation failed: {exc}")

    return json.dumps({"created": True, "lead": created})


@function_tool
def update_lead(
    ctx: RunContextWrapper[SalesContext],
    updates: LeadUpdate,
    email: str | None = None,
) -> str:
    """
    Update an existing lead's record without affecting unrelated fields. Use
    this after learning something new about a returning, already-known lead.

    products_of_interest and notes are merged/appended automatically — pass
    only the NEW products or the NEW note text, not the full accumulated
    history. lead_status, email, industry, and last_contact_date are plain
    overwrites — pass a field only if it changed.

    Args:
        updates: The fields to change. Leave a field unset (None) to leave
            it untouched.
        email: Email of the lead to update. Defaults to the current
            customer's verified email if not given.
    """
    if email is None:
        email = ctx.context.customer_email
    try:
        updated = get_lead_store().update(email, updates.model_dump(exclude_none=True))
    except CRMNotConfiguredError as exc:
        return _error_response(f"CRM is not configured yet — {exc}")
    except Exception as exc:  # noqa: BLE001 - surface update failures to the sales agent
        return _error_response(f"Lead update failed: {exc}")

    if updated is None:
        return json.dumps({"updated": False, "error": "No matching lead found to update."})
    return json.dumps({"updated": True, "lead": updated})


@function_tool
def upsert_lead(ctx: RunContextWrapper[SalesContext], lead: Lead) -> str:
    """
    Save or refresh a lead's record: updates it if it already exists (merging
    products_of_interest/notes, overwriting other changed fields), otherwise
    creates it. This is your default way to record what you've learned about
    a lead after a meaningful exchange — prefer it over create_lead/
    update_lead individually unless you specifically need "must not already
    exist" (use create_lead) or "must already exist" (use update_lead)
    behavior. Do this proactively in the background; don't ask the
    customer's permission or narrate it in your reply.

    Args:
        lead: The lead's current details. Only include products_of_interest/
            notes for what's NEW from this interaction — they're merged with
            any existing history automatically, not overwritten.
    """
    try:
        updated, was_created = get_lead_store().upsert(lead.model_dump())
    except CRMNotConfiguredError as exc:
        return _error_response(f"CRM is not configured yet — {exc}")
    except Exception as exc:  # noqa: BLE001 - surface upsert failures to the sales agent
        return _error_response(f"Lead upsert failed: {exc}")

    return json.dumps({"upserted": True, "created": was_created, "lead": updated})
