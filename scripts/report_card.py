#!/usr/bin/env python3
"""
Homeowner Solar Report Card Generator
--------------------------------------
Generates a beautiful, mobile-responsive standalone HTML report card
for a specific address. The rep can text or email this link to the homeowner
after the door knock — it's consumer-friendly (not sales-heavy).

CLI Usage:
    python scripts/report_card.py "1905 E Marquette Dr, Gilbert, AZ" --bill 175
    python scripts/report_card.py "1905 E Marquette Dr, Gilbert, AZ" --bill 175 \
        --rep-name "Jake Rivera" --rep-phone "602-555-0100" --rep-company "Elevate Solar"
    python scripts/report_card.py "1905 E Marquette Dr, Gilbert, AZ" --bill 175 \
        --output /tmp/my_report.html --open

API:
    GET  /api/lead/report-card?address=...&monthly_bill=175
         Returns standalone HTML page
    POST /api/lead/report-card
         Body: {address, monthly_bill, rep_name, rep_phone, rep_company, utility_rate}
         Returns standalone HTML page
"""

import os
import sys
import argparse
import datetime
import json

# Make importable from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.solar import enrich_lead

# ─── Grade colors ─────────────────────────────────────────────────────────────
GRADE_COLORS = {
    "A+": "#22c55e",
    "A":  "#4ade80",
    "B":  "#facc15",
    "C":  "#fb923c",
    "D":  "#f87171",
}
PRIORITY_EMOJIS = {
    "HOT":  "🔥",
    "WARM": "☀️",
    "COOL": "🌤️",
    "LOW":  "🌧️",
}


def _score_color(score: int) -> str:
    if score >= 75: return "#22c55e"
    if score >= 55: return "#facc15"
    if score >= 35: return "#fb923c"
    return "#f87171"


def _bar_pct(score: int) -> int:
    return min(100, max(0, score))


def _fmt_usd(val) -> str:
    try:
        v = float(val)
        return f"${v:,.0f}"
    except Exception:
        return str(val)


def _fmt_yr(val) -> str:
    try:
        v = float(val)
        return f"{v:.1f} yrs"
    except Exception:
        return str(val)


def build_html(lead: dict,
               rep_name: str = "",
               rep_phone: str = "",
               rep_company: str = "Solar Intelligence",
               generated_at: str = None) -> str:
    """Build the full standalone HTML report card string."""

    if "error" in lead:
        return f"<html><body><h2>Error: {lead['error']}</h2></body></html>"

    addr      = lead.get("address", "Unknown Address")
    city      = lead.get("city", "")
    state     = lead.get("state", "")
    score     = lead.get("lead_score", 0)
    grade     = lead.get("lead_grade", "?")
    priority  = lead.get("priority", "")
    bill      = lead.get("monthly_bill_usd", 175)

    sun_hrs   = lead.get("sunshine_hours_per_year", 0)
    panels    = lead.get("panels_recommended", 0)
    sys_kw    = lead.get("system_size_kw", 0)
    segments  = lead.get("roof_segments", 0)
    max_pan   = lead.get("max_panels_possible", 0)
    offset    = lead.get("offset_pct", 0)

    gross     = lead.get("gross_cost_usd", 0)
    itc       = lead.get("federal_itc_usd", 0)
    net       = lead.get("net_cost_usd", 0)
    yr1_sav   = lead.get("annual_savings_yr1_usd", 0)
    life_sav  = lead.get("lifetime_savings_usd", 0)
    payback   = lead.get("payback_years", 0)
    roi       = lead.get("roi_25yr_pct", 0)
    co2       = lead.get("co2_offset_lbs_per_year", 0)
    trees     = lead.get("trees_equivalent_per_year", 0)
    kwh       = lead.get("annual_kwh_produced", 0)

    score_color  = _score_color(score)
    grade_color  = GRADE_COLORS.get(grade, "#94a3b8")
    priority_emoji = PRIORITY_EMOJIS.get(priority, "")
    bar_pct      = _bar_pct(score)
    gen_dt       = generated_at or datetime.datetime.utcnow().strftime("%B %d, %Y")

    # Build rep footer HTML
    if rep_name or rep_company:
        rep_contact = ""
        if rep_phone:
            rep_contact = f'<a href="tel:{rep_phone}" class="rep-phone">{rep_phone}</a>'
        rep_html = f"""
        <div class="rep-card">
          <div class="rep-avatar">{(rep_name or rep_company)[0].upper()}</div>
          <div class="rep-info">
            <div class="rep-name">{rep_name or rep_company}</div>
            <div class="rep-co">{rep_company if rep_name else ""}</div>
          </div>
          {f'<div class="rep-cta">{rep_contact}</div>' if rep_contact else ''}
        </div>"""
    else:
        rep_html = ""

    # Talking points list items
    talking_pts = lead.get("talking_points", [])
    tp_html = ""
    for pt in talking_pts:
        # strip leading emoji if present for cleaner list
        tp_html += f'<li class="tp-item">{pt}</li>\n'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Solar Report Card — {city}, {state}</title>
  <style>
    /* ─── Reset & Base ─────────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
      padding: 0 0 2rem 0;
    }}
    a {{ color: inherit; text-decoration: none; }}

    /* ─── Header ────────────────────────────────────────────────────── */
    .header {{
      background: linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%);
      padding: 2rem 1.5rem 3rem;
      text-align: center;
      border-bottom: 1px solid #1e3a5f;
      position: relative;
    }}
    .sun-icon {{
      font-size: 2.5rem;
      display: block;
      margin-bottom: 0.5rem;
    }}
    .header-label {{
      font-size: 0.75rem;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      color: #64748b;
      margin-bottom: 0.25rem;
    }}
    .header-title {{
      font-size: 1.5rem;
      font-weight: 700;
      color: #f8fafc;
      margin-bottom: 0.25rem;
    }}
    .header-addr {{
      font-size: 0.9rem;
      color: #94a3b8;
      margin-bottom: 0.5rem;
    }}
    .header-date {{
      font-size: 0.75rem;
      color: #475569;
    }}

    /* ─── Score Hero Card ───────────────────────────────────────────── */
    .container {{
      max-width: 540px;
      margin: -1.5rem auto 0;
      padding: 0 1rem;
    }}
    .score-hero {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 1rem;
      padding: 1.5rem;
      text-align: center;
      margin-bottom: 1rem;
      box-shadow: 0 4px 24px rgba(0,0,0,0.4);
    }}
    .score-ring {{
      width: 110px;
      height: 110px;
      border-radius: 50%;
      border: 8px solid {score_color};
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 0.75rem;
      box-shadow: 0 0 24px {score_color}55;
      flex-direction: column;
    }}
    .score-num {{
      font-size: 2rem;
      font-weight: 800;
      color: {score_color};
      line-height: 1;
    }}
    .score-denom {{
      font-size: 0.65rem;
      color: #64748b;
    }}
    .grade-badge {{
      display: inline-block;
      background: {grade_color};
      color: #0f172a;
      font-weight: 800;
      font-size: 0.9rem;
      padding: 0.2rem 0.75rem;
      border-radius: 999px;
      margin-bottom: 0.5rem;
    }}
    .priority-tag {{
      font-size: 0.8rem;
      color: #94a3b8;
      margin-bottom: 0.75rem;
    }}
    /* Score bar */
    .score-bar-wrap {{
      background: #0f172a;
      border-radius: 999px;
      height: 8px;
      overflow: hidden;
      margin: 0.5rem 0 0;
    }}
    .score-bar-fill {{
      height: 100%;
      width: {bar_pct}%;
      background: linear-gradient(90deg, {score_color}88, {score_color});
      border-radius: 999px;
      transition: width 1s ease;
    }}
    .score-bar-labels {{
      display: flex;
      justify-content: space-between;
      font-size: 0.65rem;
      color: #475569;
      margin-top: 0.2rem;
    }}

    /* ─── Stat Grid ─────────────────────────────────────────────────── */
    .section-title {{
      font-size: 0.7rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #475569;
      margin: 1.25rem 0 0.5rem;
    }}
    .stat-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.75rem;
      margin-bottom: 0.75rem;
    }}
    .stat-card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 0.75rem;
      padding: 1rem;
    }}
    .stat-icon {{ font-size: 1.25rem; margin-bottom: 0.25rem; }}
    .stat-val {{
      font-size: 1.25rem;
      font-weight: 700;
      color: #f1f5f9;
      line-height: 1.1;
    }}
    .stat-label {{
      font-size: 0.7rem;
      color: #64748b;
      margin-top: 0.1rem;
    }}
    .stat-card.accent {{
      border-color: {score_color}55;
      background: linear-gradient(135deg, #1e293b, #1a2f1a);
    }}
    .stat-card.accent .stat-val {{ color: {score_color}; }}

    /* ─── Highlight Bar ─────────────────────────────────────────────── */
    .highlight-bar {{
      background: linear-gradient(135deg, #1e3a5f, #1e293b);
      border: 1px solid #1e3a5f;
      border-radius: 0.75rem;
      padding: 1rem 1.25rem;
      margin-bottom: 0.75rem;
      display: flex;
      align-items: center;
      gap: 1rem;
    }}
    .hl-emoji {{ font-size: 2rem; flex-shrink: 0; }}
    .hl-text .hl-val {{
      font-size: 1.5rem;
      font-weight: 800;
      color: #38bdf8;
    }}
    .hl-text .hl-label {{
      font-size: 0.75rem;
      color: #64748b;
    }}

    /* ─── Talking Points ────────────────────────────────────────────── */
    .tp-list {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }}
    .tp-item {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 0.5rem;
      padding: 0.65rem 0.9rem;
      font-size: 0.82rem;
      color: #cbd5e1;
      line-height: 1.45;
    }}

    /* ─── Timeline / Next Steps ─────────────────────────────────────── */
    .steps-card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 0.75rem;
      padding: 1.25rem;
      margin-bottom: 0.75rem;
    }}
    .step-row {{
      display: flex;
      align-items: flex-start;
      gap: 0.75rem;
      padding: 0.5rem 0;
      border-bottom: 1px solid #0f172a;
    }}
    .step-row:last-child {{ border-bottom: none; }}
    .step-num {{
      width: 1.5rem;
      height: 1.5rem;
      border-radius: 50%;
      background: #0f172a;
      border: 2px solid {score_color};
      color: {score_color};
      font-weight: 700;
      font-size: 0.7rem;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }}
    .step-text {{ font-size: 0.82rem; color: #cbd5e1; line-height: 1.4; }}
    .step-text strong {{ color: #f1f5f9; }}

    /* ─── Rep Footer ────────────────────────────────────────────────── */
    .rep-card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 0.75rem;
      padding: 1rem 1.25rem;
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-top: 1.25rem;
    }}
    .rep-avatar {{
      width: 2.5rem;
      height: 2.5rem;
      border-radius: 50%;
      background: linear-gradient(135deg, {score_color}, #38bdf8);
      color: #0f172a;
      font-weight: 800;
      font-size: 1.1rem;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }}
    .rep-name {{ font-weight: 700; font-size: 0.9rem; }}
    .rep-co {{ font-size: 0.75rem; color: #64748b; }}
    .rep-cta {{ margin-left: auto; }}
    .rep-phone {{
      background: {score_color};
      color: #0f172a;
      font-weight: 700;
      font-size: 0.8rem;
      padding: 0.4rem 0.9rem;
      border-radius: 999px;
      display: block;
    }}

    /* ─── Footer note ───────────────────────────────────────────────── */
    .footer-note {{
      text-align: center;
      font-size: 0.65rem;
      color: #334155;
      margin-top: 1.5rem;
      padding: 0 1rem;
    }}
  </style>
</head>
<body>
  <!-- Header -->
  <div class="header">
    <span class="sun-icon">☀️</span>
    <div class="header-label">Solar Intelligence Suite</div>
    <div class="header-title">Your Home's Solar Profile</div>
    <div class="header-addr">{addr}</div>
    <div class="header-date">Generated {gen_dt}</div>
  </div>

  <div class="container">

    <!-- Score Hero -->
    <div class="score-hero">
      <div class="score-ring">
        <div class="score-num">{score}</div>
        <div class="score-denom">/100</div>
      </div>
      <div class="grade-badge">{grade}</div>
      <div class="priority-tag">{priority_emoji} {priority} Solar Candidate</div>
      <div class="score-bar-wrap">
        <div class="score-bar-fill"></div>
      </div>
      <div class="score-bar-labels">
        <span>Low</span><span>Good</span><span>Excellent</span>
      </div>
    </div>

    <!-- Key Savings Highlight -->
    <div class="highlight-bar">
      <div class="hl-emoji">💰</div>
      <div class="hl-text">
        <div class="hl-val">{_fmt_usd(yr1_sav)}/yr</div>
        <div class="hl-label">Estimated first-year electricity savings</div>
      </div>
    </div>
    <div class="highlight-bar">
      <div class="hl-emoji">🏛️</div>
      <div class="hl-text">
        <div class="hl-val">{_fmt_usd(itc)} off</div>
        <div class="hl-label">30% Federal Solar Tax Credit (ITC) — immediate</div>
      </div>
    </div>

    <!-- Solar Stats -->
    <div class="section-title">☀️ Your Roof's Solar Potential</div>
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-icon">🌞</div>
        <div class="stat-val">{sun_hrs:,.0f}</div>
        <div class="stat-label">Sun hours per year</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">⚡</div>
        <div class="stat-val">{sys_kw} kW</div>
        <div class="stat-label">Recommended system size</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">🔲</div>
        <div class="stat-val">{panels} panels</div>
        <div class="stat-label">Recommended ({max_pan} max possible)</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">📊</div>
        <div class="stat-val">{offset:.0f}%</div>
        <div class="stat-label">Energy offset achieved</div>
      </div>
    </div>

    <!-- Financial Stats -->
    <div class="section-title">💵 Financial Snapshot</div>
    <div class="stat-grid">
      <div class="stat-card accent">
        <div class="stat-icon">💲</div>
        <div class="stat-val">{_fmt_usd(net)}</div>
        <div class="stat-label">Net cost after 30% ITC</div>
      </div>
      <div class="stat-card accent">
        <div class="stat-icon">📅</div>
        <div class="stat-val">{_fmt_yr(payback)}</div>
        <div class="stat-label">Estimated payback period</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">📈</div>
        <div class="stat-val">{roi:.0f}%</div>
        <div class="stat-label">25-year ROI</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">🏆</div>
        <div class="stat-val">{_fmt_usd(life_sav)}</div>
        <div class="stat-label">Lifetime savings (25 yr)</div>
      </div>
    </div>

    <!-- Environmental Impact -->
    <div class="section-title">🌱 Environmental Impact</div>
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-icon">🌳</div>
        <div class="stat-val">{trees:.0f} trees</div>
        <div class="stat-label">Equivalent planted per year</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">🌍</div>
        <div class="stat-val">{co2/2000:.1f} tons</div>
        <div class="stat-label">CO₂ offset per year</div>
      </div>
    </div>

    <!-- Key Talking Points -->
    <div class="section-title">📋 Key Numbers At A Glance</div>
    <ul class="tp-list">
      {tp_html}
    </ul>

    <!-- Next Steps -->
    <div class="section-title">🚀 Your Next Steps</div>
    <div class="steps-card">
      <div class="step-row">
        <div class="step-num">1</div>
        <div class="step-text"><strong>Review this report</strong> — share it with your spouse or partner. All numbers are personalized to your home.</div>
      </div>
      <div class="step-row">
        <div class="step-num">2</div>
        <div class="step-text"><strong>Check your last 3 utility bills</strong> — we'll use the real numbers to fine-tune your savings estimate.</div>
      </div>
      <div class="step-row">
        <div class="step-num">3</div>
        <div class="step-text"><strong>Get your free site assessment</strong> — no pressure, no cost. We'll confirm roof condition and finalize your system design.</div>
      </div>
      <div class="step-row">
        <div class="step-num">4</div>
        <div class="step-text"><strong>Lock in 2024 ITC pricing</strong> — the 30% federal tax credit is available now. Rates and panel costs change regularly.</div>
      </div>
    </div>

    <!-- Rep Card -->
    {rep_html}

    <p class="footer-note">
      Report generated by Solar Intelligence Suite · Satellite data powered by Google Solar API ·
      Estimates based on {_fmt_usd(bill)}/mo utility bill · Individual results may vary ·
      Consult a licensed solar installer for final system design.
    </p>

  </div>
</body>
</html>"""

    return html


def generate_report_card(address: str,
                         monthly_bill: float = 175.0,
                         utility_rate: float = 0.14,
                         rep_name: str = "",
                         rep_phone: str = "",
                         rep_company: str = "Solar Intelligence",
                         output_path: str = None) -> dict:
    """
    Enrich address → build HTML report card → save to cache/.
    Returns {'html': str, 'path': str, 'lead': dict, 'error': str|None}
    """
    lead = enrich_lead(address, monthly_bill=monthly_bill, utility_rate=utility_rate)
    if "error" in lead:
        return {"error": lead["error"], "html": None, "path": None, "lead": lead}

    html = build_html(lead, rep_name=rep_name, rep_phone=rep_phone, rep_company=rep_company)

    # Auto-path: cache/report_card_<slug>_<date>.html
    if not output_path:
        slug = lead.get("address", address).replace(",", "").replace(" ", "_")[:40]
        date_str = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M")
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        output_path = os.path.join(cache_dir, f"report_card_{slug}_{date_str}.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return {"html": html, "path": output_path, "lead": lead, "error": None}


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a homeowner solar report card HTML page.")
    parser.add_argument("address", help="Property address to analyze")
    parser.add_argument("--bill", type=float, default=175.0, metavar="DOLLARS",
                        help="Monthly utility bill in USD (default: 175)")
    parser.add_argument("--rate", type=float, default=0.14, metavar="RATE",
                        help="Utility rate per kWh (default: 0.14)")
    parser.add_argument("--rep-name", default="", metavar="NAME",
                        help="Rep's name for footer card")
    parser.add_argument("--rep-phone", default="", metavar="PHONE",
                        help="Rep's phone number for footer CTA")
    parser.add_argument("--rep-company", default="Solar Intelligence", metavar="COMPANY",
                        help="Company name (default: Solar Intelligence)")
    parser.add_argument("--output", default=None, metavar="PATH",
                        help="Custom output HTML path")
    parser.add_argument("--open", action="store_true",
                        help="Open HTML in browser after generating")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Print JSON summary to stdout instead of HTML path")
    args = parser.parse_args()

    result = generate_report_card(
        args.address,
        monthly_bill=args.bill,
        utility_rate=args.rate,
        rep_name=args.rep_name,
        rep_phone=args.rep_phone,
        rep_company=args.rep_company,
        output_path=args.output,
    )

    if result.get("error"):
        print(f"❌ Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    lead = result["lead"]
    path = result["path"]

    if args.json_out:
        print(json.dumps({
            "address": lead.get("address"),
            "score": lead.get("lead_score"),
            "grade": lead.get("lead_grade"),
            "priority": lead.get("priority"),
            "annual_savings": lead.get("annual_savings_yr1_usd"),
            "net_cost": lead.get("net_cost_usd"),
            "payback_years": lead.get("payback_years"),
            "output_path": path,
        }, indent=2))
    else:
        # Pretty terminal summary
        grade    = lead.get("lead_grade", "?")
        score    = lead.get("lead_score", 0)
        priority = lead.get("priority", "")
        yr1      = lead.get("annual_savings_yr1_usd", 0)
        net      = lead.get("net_cost_usd", 0)
        payback  = lead.get("payback_years", 0)

        BOLD  = "\033[1m"
        GREEN = "\033[92m"
        CYAN  = "\033[96m"
        RESET = "\033[0m"

        print(f"\n{BOLD}☀️  Solar Report Card Generated{RESET}")
        print(f"   Address : {lead.get('address')}")
        print(f"   Score   : {GREEN}{BOLD}{score}/100{RESET}  Grade: {BOLD}{grade}{RESET}  Priority: {priority}")
        print(f"   Yr1 Sav : {CYAN}${yr1:,.0f}{RESET}  Net Cost: ${net:,.0f}  Payback: {payback:.1f} yrs")
        print(f"\n{BOLD}📄 Report saved to:{RESET}")
        print(f"   {path}\n")

    if args.open:
        import subprocess
        subprocess.Popen(["xdg-open", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
