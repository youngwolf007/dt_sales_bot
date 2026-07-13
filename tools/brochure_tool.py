"""PDF brochure rendering helpers, used by tools/email_tool.py to attach a
brochure to the proposal email. Not a standalone agent tool — the brochure is
always sent together with the proposal in one email, not requested separately."""

import re
from datetime import date
from html import escape
from io import BytesIO

from xhtml2pdf import pisa

from models import DTSolution

MAGENTA = "#E20074"
DARK_GRAY = "#333333"
MID_GRAY = "#666666"
LIGHT_GRAY = "#F7F7F7"
BORDER_GRAY = "#DDDDDD"

BROCHURE_CSS = f"""
@page {{
  size: A4;
  margin: 20mm 18mm;
  @frame footer_frame {{
    -pdf-frame-content: footerContent;
    bottom: 1cm; margin-left: 18mm; margin-right: 18mm; height: 1cm;
  }}
}}
body {{ font-family: Helvetica, Arial, sans-serif; color: {DARK_GRAY}; font-size: 10.5pt; line-height: 1.5; }}
h1 {{ color: {MAGENTA}; font-size: 20pt; margin: 0 0 4mm; }}
h2 {{ color: {DARK_GRAY}; font-size: 14pt; border-bottom: 2px solid {MAGENTA}; padding-bottom: 2mm; margin-top: 8mm; }}
h3 {{ color: {MAGENTA}; font-size: 12pt; margin: 0 0 1mm; }}
.label {{ color: {MID_GRAY}; font-size: 8.5pt; text-transform: uppercase; margin: 3mm 0 0.5mm; font-weight: bold; }}

.cover {{ page-break-after: always; padding-top: 15mm; text-align: center; }}
.cover-wordmark {{ color: {MAGENTA}; font-size: 15pt; font-weight: bold; letter-spacing: 3px; }}
.cover-rule {{ width: 36mm; height: 2px; background: {MAGENTA}; margin: 4mm auto 8mm; }}
.cover-title {{ color: {DARK_GRAY}; font-size: 27pt; font-weight: normal; }}
.cover-prepared {{ color: {MID_GRAY}; font-size: 12pt; margin-top: 12mm; }}
.cover-company {{ color: {DARK_GRAY}; font-size: 16pt; font-weight: bold; }}
.cover-date {{ color: {MID_GRAY}; font-size: 10pt; margin-top: 4mm; }}
.cover-confidential {{ color: {MID_GRAY}; font-size: 9pt; margin-top: 12mm; letter-spacing: 2px; }}

table.summary {{ width: 100%; border-collapse: collapse; margin-top: 3mm; }}
table.summary th {{ background: {LIGHT_GRAY}; text-align: left; padding: 2mm; border: 1px solid {BORDER_GRAY}; font-size: 9.5pt; }}
table.summary td {{ padding: 2mm; border: 1px solid {BORDER_GRAY}; font-size: 9.5pt; }}

.category-heading {{ color: {MID_GRAY}; font-size: 10pt; text-transform: uppercase; letter-spacing: 1px;
  margin-top: 8mm; margin-bottom: 2mm; border-bottom: 1px solid {BORDER_GRAY}; padding-bottom: 1mm; }}

table.solution {{ width: 100%; border-collapse: collapse; margin-bottom: 5mm; page-break-inside: avoid; }}
table.solution td {{ background: {LIGHT_GRAY}; border-left: 4px solid {MAGENTA}; padding: 4mm; }}
.category-tag {{ color: {MID_GRAY}; font-size: 8.5pt; text-transform: uppercase; margin: 0 0 2mm; }}
.feature {{ margin: 0.5mm 0; }}
.source-link {{ font-size: 9pt; margin-top: 2mm; }}

.disclaimer {{ color: {MID_GRAY}; font-size: 8pt; margin-top: 10mm; border-top: 1px solid {BORDER_GRAY}; padding-top: 3mm; }}
.contact {{ margin-top: 6mm; font-size: 9.5pt; }}

#footerContent {{ color: {MID_GRAY}; font-size: 8pt; text-align: right; }}
"""


def _group_by_category(solutions: list[DTSolution]) -> dict[str, list[DTSolution]]:
    groups: dict[str, list[DTSolution]] = {}
    for solution in solutions:
        groups.setdefault(solution.category, []).append(solution)
    return groups


def _render_cover(prepared_for: str | None) -> str:
    company = escape(prepared_for) if prepared_for else "Your Business"
    return f"""
    <div class="cover">
      <div class="cover-wordmark">DEUTSCHE TELEKOM</div>
      <div class="cover-rule"></div>
      <div class="cover-title">Business Solutions</div>
      <div class="cover-prepared">Prepared for<br/><span class="cover-company">{company}</span></div>
      <div class="cover-date">{date.today().strftime("%d %B %Y")}</div>
      <div class="cover-confidential">CONFIDENTIAL</div>
    </div>
    """


def _render_summary(solutions: list[DTSolution], business_need: str | None) -> str:
    need_block = f"<p>{escape(business_need)}</p>" if business_need else ""

    rows = ""
    for solution in solutions:
        rows += (
            f"<tr><td>{escape(solution.name)}</td><td>{escape(solution.category)}</td>"
            f"<td>{escape(solution.fit_rationale)}</td></tr>"
        )

    why_items = "".join(
        f'<p class="feature">&#10003; {escape(solution.fit_rationale)}</p>' for solution in solutions
    )

    return f"""
    <h2>Executive Summary</h2>
    {need_block}
    <p class="label">Recommended Solutions</p>
    <table class="summary">
      <tr><th>Solution</th><th>Category</th><th>Key Benefit</th></tr>
      {rows}
    </table>
    <p class="label">Why These Recommendations</p>
    {why_items}
    """


def _render_solution_card(solution: DTSolution) -> str:
    features = "".join(f'<p class="feature">&#10003; {escape(feature)}</p>' for feature in solution.key_features)
    source = (
        f'<p class="source-link"><a href="{escape(solution.source_url)}">{escape(solution.source_url)}</a></p>'
        if solution.source_url
        else ""
    )
    return f"""
    <table class="solution"><tr><td>
      <h3>{escape(solution.name)}</h3>
      <p class="category-tag">{escape(solution.category)}</p>
      <p class="label">Description</p>
      <p>{escape(solution.description)}</p>
      <p class="label">Key Benefits</p>
      {features}
      <p class="label">Why This Matches</p>
      <p>{escape(solution.fit_rationale)}</p>
      {source}
    </td></tr></table>
    """


def _render_brochure_html(solutions: list[DTSolution], prepared_for: str | None, business_need: str | None) -> str:
    body = _render_summary(solutions, business_need)

    for category, group in _group_by_category(solutions).items():
        heading = f'<div class="category-heading">{escape(category)}</div>'
        first_card = _render_solution_card(group[0])
        # Glue the heading to its first card so it can't be orphaned alone at
        # the bottom of a page — page-break-inside only works reliably here
        # when heading + card are inside one table cell.
        body += f'<table style="width:100%;border-collapse:collapse;page-break-inside:avoid;">' \
                f'<tr><td style="padding:0;">{heading}{first_card}</td></tr></table>'
        body += "".join(_render_solution_card(solution) for solution in group[1:])

    return f"""
    <html>
      <head><style>{BROCHURE_CSS}</style></head>
      <body>
        {_render_cover(prepared_for)}
        {body}
        <div class="disclaimer">
          The recommendations in this brochure are based on the information provided
          during our discussion. Availability of products may vary by region. Final
          pricing and implementation are subject to commercial review.
        </div>
        <div class="contact">
          <strong>Need help?</strong><br/>
          Reach out to your Deutsche Telekom Business Solutions Advisor, or use the
          links above to learn more about each solution directly.
        </div>
        <div id="footerContent">
          Deutsche Telekom Business Solutions &middot; Page <pdf:pagenumber /> of <pdf:pagecount />
        </div>
      </body>
    </html>
    """


def _render_brochure_pdf(solutions: list[DTSolution], prepared_for: str | None, business_need: str | None) -> bytes:
    html = _render_brochure_html(solutions, prepared_for, business_need)
    buffer = BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)
    if result.err:
        raise RuntimeError(f"PDF generation failed with {result.err} error(s)")
    return buffer.getvalue()


def _brochure_filename(prepared_for: str | None) -> str:
    base = "DT_Business_Solutions"
    if prepared_for:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", prepared_for).strip("_")
        if slug:
            base = f"{base}_{slug}"
    return f"{base}_{date.today().isoformat()}.pdf"
