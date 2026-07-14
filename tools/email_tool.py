import re
import smtplib
from email.message import EmailMessage
from html import escape

from agents import RunContextWrapper, function_tool

from config import EMAIL_ADDRESS, EMAIL_APP_PASSWORD, EMAIL_SMTP_SERVER
from context import SalesContext
from models import ProposalContent
from tools.brochure_tool import _brochure_filename, _render_brochure_pdf
from trusted_domains import sanitize_solutions

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _sanitize_proposal(proposal: ProposalContent) -> ProposalContent:
    """Defense in depth: the agent composes ProposalContent itself when calling
    this tool, so re-verify every link here rather than trusting it was carried
    over correctly from a prior research result."""
    return proposal.model_copy(update={"recommended_solutions": sanitize_solutions(proposal.recommended_solutions)})


def send_email(
    recipient_email: str,
    subject: str,
    text_body: str,
    html_body: str,
    attachment: tuple[str, bytes, str] | None = None,
) -> None:
    """attachment, if given, is (filename, content_bytes, subtype) e.g. ("brochure.pdf", pdf_bytes, "pdf")."""
    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    if attachment:
        filename, content, subtype = attachment
        msg.add_attachment(content, maintype="application", subtype=subtype, filename=filename)

    with smtplib.SMTP(EMAIL_SMTP_SERVER, 587) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        server.send_message(msg)


def _render_text(proposal: ProposalContent) -> str:
    lines = [
        f"Deutsche Telekom Business Proposal for {proposal.customer_name}",
        "",
        "Company snapshot:",
        proposal.company_snapshot,
        "",
        "Requirements summary:",
        proposal.requirements_summary,
        "",
        "Recommended solutions:",
    ]
    for solution in proposal.recommended_solutions:
        lines.append(f"\n- {solution.name} ({solution.category})")
        lines.append(f"  {solution.description}")
        if solution.key_features:
            lines.append(f"  Key features: {', '.join(solution.key_features)}")
        lines.append(f"  Why it fits: {solution.fit_rationale}")
        if solution.source_url:
            lines.append(f"  Learn more & proceed: {solution.source_url}")
    lines += ["", "Next steps:", proposal.next_steps]
    return "\n".join(lines)


def _render_html(proposal: ProposalContent) -> str:
    solution_blocks = ""
    for solution in proposal.recommended_solutions:
        features = "".join(f"<li>{escape(feature)}</li>" for feature in solution.key_features)
        cta = (
            f'<p style="margin-top:12px;">'
            f'<a href="{escape(solution.source_url)}" '
            'style="display:inline-block;padding:8px 16px;background:#e20074;color:#fff;'
            'text-decoration:none;border-radius:4px;font-size:14px;">Learn more &amp; proceed →</a>'
            "</p>"
            if solution.source_url
            else ""
        )
        solution_blocks += f"""
        <div style="margin-bottom:20px;padding:16px;border:1px solid #e0e0e0;border-radius:8px;">
          <h3 style="color:#e20074;margin:0 0 4px;">{escape(solution.name)}</h3>
          <p style="color:#666;margin:0 0 8px;font-size:13px;text-transform:uppercase;">{escape(solution.category)}</p>
          <p>{escape(solution.description)}</p>
          <ul>{features}</ul>
          <p><strong>Why it fits:</strong> {escape(solution.fit_rationale)}</p>
          {cta}
        </div>
        """

    return f"""
    <html>
      <body style="font-family:Arial,sans-serif;color:#222;max-width:640px;margin:auto;">
        <h1 style="color:#e20074;">Deutsche Telekom Business Proposal</h1>
        <p>Prepared for <strong>{escape(proposal.customer_name)}</strong></p>

        <h2>Company snapshot</h2>
        <p>{escape(proposal.company_snapshot)}</p>

        <h2>Your requirements</h2>
        <p>{escape(proposal.requirements_summary)}</p>

        <h2>Recommended solutions</h2>
        {solution_blocks}

        <h2>Next steps</h2>
        <p>{escape(proposal.next_steps)}</p>
      </body>
    </html>
    """


@function_tool
def send_proposal_email(
    ctx: RunContextWrapper[SalesContext],
    proposal: ProposalContent,
    recipient_email: str | None = None,
) -> str:
    """
    Send the finalized business proposal to the customer by email, as a
    single email: the written proposal in the body, plus a PDF brochure of
    the recommended solutions attached.

    Only call this after the sales agent has summarized the proposed solution(s)
    back to the user and received their explicit confirmation to send.

    Args:
        proposal: The structured proposal content to render and send.
        recipient_email: The customer's email address. Usually you can omit
            this — it defaults to the customer's verified login email.
    """
    # Cleared up front so a failed call never leaves a stale success from an
    # earlier proposal for the sales agent's on_tool_end hook to pick up.
    ctx.context.last_sent_proposal = None
    ctx.context.last_sent_proposal_recipient = None

    recipient_email = recipient_email or ctx.context.customer_email

    if not EMAIL_RE.match(recipient_email):
        return f"Could not send: '{recipient_email}' does not look like a valid email address."

    proposal = _sanitize_proposal(proposal)
    subject = f"Your Deutsche Telekom Business Proposal — {proposal.customer_name}"
    text_body = _render_text(proposal)
    html_body = _render_html(proposal)

    attachment = None
    pdf_error = None
    try:
        pdf_bytes = _render_brochure_pdf(proposal.recommended_solutions, proposal.customer_name, proposal.requirements_summary)
        attachment = (_brochure_filename(proposal.customer_name), pdf_bytes, "pdf")
    except Exception as exc:  # noqa: BLE001 - don't block the email over a PDF failure, just report it
        pdf_error = str(exc)

    try:
        send_email(recipient_email, subject, text_body, html_body, attachment=attachment)
    except Exception as exc:  # noqa: BLE001 - surface any SMTP failure back to the agent
        return f"Failed to send email to {recipient_email}: {exc}"

    # Recorded here purely as data for the sales agent's own on_tool_end hook
    # (see agents_def/sales_agent.py) to act on — this tool's job is sending
    # the email, not deciding what goes into the CRM.
    ctx.context.last_sent_proposal = proposal
    ctx.context.last_sent_proposal_recipient = recipient_email

    if pdf_error:
        return (
            f"Proposal email sent to {recipient_email}, but the PDF brochure could not be "
            f"attached: {pdf_error}. Let the customer know it's coming separately or offer to retry."
        )
    return f"Proposal email (with PDF brochure attached) sent successfully to {recipient_email}."
