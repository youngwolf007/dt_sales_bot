"""Google-Sheets-backed implementation of crm.base.LeadStore.

Auth is a GCP service account (no interactive OAuth flow is feasible for a
headless bot). The client/worksheet handle is created lazily on first real
use, so importing this module never fails even if Sheets isn't configured —
that failure is deferred to CRMNotConfiguredError, raised inside a tool call
where it can be turned into a clean JSON error instead of crashing the agent.
"""

import logging
from datetime import date, datetime, timezone

import gspread
import requests
from google.oauth2.service_account import Credentials

from config import GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_SHEET_ID, GOOGLE_SHEETS_WORKSHEET_NAME
from crm.base import call_with_retry
from crm.matching import append_note, company_matches, emails_match, merge_products

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Single source of truth for sheet column order <-> the snake_case keys used
# everywhere else (matches models.Lead's field names, minus created_at/updated_at
# which the store manages itself rather than accepting as LLM input).
FIELD_TO_HEADER = {
    "name": "Name",
    "company": "Company",
    "email": "Email",
    "industry": "Industry",
    "lead_status": "Lead Status",
    "products_of_interest": "Products of Interest",
    "notes": "Notes",
    "last_contact_date": "Last Contact Date",
    "created_at": "Created At",
    "updated_at": "Updated At",
}
SHEET_HEADERS = list(FIELD_TO_HEADER.values())
MERGE_FIELDS = {"products_of_interest", "notes"}

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class CRMNotConfiguredError(Exception):
    """Raised when required Google Sheets env vars are missing."""


class LeadAlreadyExistsError(Exception):
    """Raised by create() when a lead with the same email already exists."""

    def __init__(self, existing: dict):
        super().__init__(f"Lead already exists: {existing.get('email')}")
        self.existing = existing


def _is_retryable_api_error(exc: BaseException) -> bool:
    if isinstance(exc, gspread.exceptions.APIError):
        return exc.code in _RETRYABLE_STATUS
    return isinstance(exc, requests.exceptions.RequestException)


def _row_to_dict(row: list[str]) -> dict:
    padded = row + [""] * (len(SHEET_HEADERS) - len(row))
    by_header = dict(zip(SHEET_HEADERS, padded))
    return {field: by_header.get(header, "") for field, header in FIELD_TO_HEADER.items()}


def _dict_to_row(lead: dict) -> list[str]:
    return [str(lead.get(field, "") or "") for field in FIELD_TO_HEADER]


class GoogleSheetsLeadStore:
    def __init__(self):
        self._worksheet = None

    def _client(self) -> gspread.Client:
        if not GOOGLE_APPLICATION_CREDENTIALS or not GOOGLE_SHEET_ID:
            raise CRMNotConfiguredError("GOOGLE_APPLICATION_CREDENTIALS and GOOGLE_SHEET_ID must both be set.")
        try:
            creds = Credentials.from_service_account_file(GOOGLE_APPLICATION_CREDENTIALS, scopes=SCOPES)
        except FileNotFoundError as exc:
            raise CRMNotConfiguredError(f"Google Sheets credentials file not found: {exc}") from exc
        return gspread.authorize(creds)

    def _get_worksheet(self):
        if self._worksheet is None:
            client = self._client()
            try:
                spreadsheet = call_with_retry(
                    client.open_by_key,
                    GOOGLE_SHEET_ID,
                    retry_on=(gspread.exceptions.APIError, requests.exceptions.RequestException),
                    is_retryable=_is_retryable_api_error,
                )
            except PermissionError as exc:
                # gspread converts a 403 APIError into a bare PermissionError
                # with no message of its own — recover the real reason (e.g.
                # Sheets API not enabled, or the sheet not shared with the
                # service account) from the chained cause instead of losing it.
                reason = str(exc.__cause__) if exc.__cause__ else str(exc)
                raise PermissionError(f"Access denied opening the spreadsheet: {reason}") from exc
            worksheet = spreadsheet.worksheet(GOOGLE_SHEETS_WORKSHEET_NAME)
            self._ensure_header(worksheet)
            self._worksheet = worksheet
        return self._worksheet

    def _ensure_header(self, worksheet) -> None:
        values = call_with_retry(
            worksheet.get_all_values,
            retry_on=(gspread.exceptions.APIError, requests.exceptions.RequestException),
            is_retryable=_is_retryable_api_error,
        )
        if not values or not values[0]:
            # A brand-new blank sheet returns [[]] (one "row" with no cells),
            # not [] — check both so a genuinely empty sheet still gets its
            # header written instead of falling through to the mismatch warning.
            call_with_retry(
                worksheet.append_row,
                SHEET_HEADERS,
                value_input_option="RAW",
                retry_on=(gspread.exceptions.APIError, requests.exceptions.RequestException),
                is_retryable=_is_retryable_api_error,
            )
        elif values[0] != SHEET_HEADERS:
            logger.warning(
                "Leads sheet header row doesn't match the expected columns %s (found %s) — "
                "proceeding without modifying it.",
                SHEET_HEADERS,
                values[0],
            )

    def _all_rows(self) -> list[dict]:
        worksheet = self._get_worksheet()
        values = call_with_retry(
            worksheet.get_all_values,
            retry_on=(gspread.exceptions.APIError, requests.exceptions.RequestException),
            is_retryable=_is_retryable_api_error,
        )
        rows = []
        for i, raw_row in enumerate(values[1:], start=2):
            lead = _row_to_dict(raw_row)
            lead["_row_number"] = i
            rows.append(lead)
        return rows

    def _find_by_identity(self, email: str | None) -> dict | None:
        if not email:
            return None
        rows = self._all_rows()
        for row in rows:
            if emails_match(email, row.get("email")):
                return row
        return None

    def search(self, email: str | None, company: str | None) -> list[dict]:
        rows = self._all_rows()
        matches: list[dict] = []
        if email:
            matches = [r for r in rows if emails_match(email, r.get("email"))]
        if not matches and company:
            matches = [r for r in rows if company_matches(company, r.get("company"))]
        return [{k: v for k, v in r.items() if k != "_row_number"} for r in matches]

    def create(self, lead: dict) -> dict:
        existing = self._find_by_identity(lead.get("email"))
        if existing is not None:
            raise LeadAlreadyExistsError({k: v for k, v in existing.items() if k != "_row_number"})

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record = dict(lead)
        if not record.get("lead_status"):
            record["lead_status"] = "New"
        if not record.get("last_contact_date"):
            record["last_contact_date"] = date.today().isoformat()
        record["created_at"] = now
        record["updated_at"] = now

        worksheet = self._get_worksheet()
        call_with_retry(
            worksheet.append_row,
            _dict_to_row(record),
            value_input_option="RAW",
            retry_on=(gspread.exceptions.APIError, requests.exceptions.RequestException),
            is_retryable=_is_retryable_api_error,
        )
        return record

    def update(self, email: str | None, updates: dict) -> dict | None:
        existing = self._find_by_identity(email)
        if existing is None:
            return None

        row_number = existing["_row_number"]
        record = {k: v for k, v in existing.items() if k != "_row_number"}
        for field, value in updates.items():
            if value is None or field not in FIELD_TO_HEADER:
                continue
            if field == "products_of_interest":
                record[field] = merge_products(record.get(field), value)
            elif field == "notes":
                record[field] = append_note(record.get(field), value)
            else:
                record[field] = value
        record["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        worksheet = self._get_worksheet()
        last_col = chr(ord("A") + len(SHEET_HEADERS) - 1)
        call_with_retry(
            worksheet.update,
            values=[_dict_to_row(record)],
            range_name=f"A{row_number}:{last_col}{row_number}",
            value_input_option="RAW",
            retry_on=(gspread.exceptions.APIError, requests.exceptions.RequestException),
            is_retryable=_is_retryable_api_error,
        )
        return record

    def upsert(self, lead: dict) -> tuple[dict, bool]:
        existing = self._find_by_identity(lead.get("email"))
        if existing is None:
            return self.create(lead), True
        updates = {k: v for k, v in lead.items() if k not in ("created_at", "updated_at")}
        updated = self.update(lead.get("email"), updates)
        assert updated is not None
        return updated, False


_store: GoogleSheetsLeadStore | None = None


def get_lead_store() -> GoogleSheetsLeadStore:
    global _store
    if _store is None:
        _store = GoogleSheetsLeadStore()
    return _store
