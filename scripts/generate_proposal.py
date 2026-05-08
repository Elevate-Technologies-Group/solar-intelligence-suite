#!/usr/bin/env python3
"""
generate_proposal.py — Solar Intelligence Suite
Generates a beautiful, standalone HTML proposal for a homeowner.
Reps can text/email this directly from the door.

Usage:
  python scripts/generate_proposal.py "1905 E Marquette Dr, Gilbert AZ 85234"
  python scripts/generate_proposal.py "address" --bill 195 --name "The Garcia Family" --rep "Jake Torres"
  python scripts/generate_proposal.py "address" --bill 195 --output /tmp/proposal.html
  python scripts/generate_proposal.py "address" --print-url   # prints file path for browser open
"""

import sys, os, argparse, json, re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/root/solar-tools")
from core.solar import enrich_lead

# ── helpers ────────────────────────────────────────────────────────────────────

def fmt_usd(n: float, cents: bool = False) -> str:
    if cents:
        return f"${n:,.2f}"
    return f"${int(round(n)):,}"

def fmt_num(n: float, dec: int = 0) -> str:
    if dec == 0:
        return f"{int(round(n)):,}"
    return f"{n:,.{dec}f}"

def progress_bar(pct: float, width: int = 20) -> str:
    filled = int(min(pct / 100, 1) * width)
    return "█" * filled + "░" * (width - filled)

def score_color(score: int) -> str:
    if score >= 68: return "#10b981"  # green
    if score >= 52: return "#f59e0b"  # amber
    return "#3b82f6"                   # blue

# ── HTML proposal template ─────────────────────────────────────────────────────

def render_proposal(lead: dict, homeowner_name: str = "", rep_name: str = "", company_name: str = "Elevate Solar") -> str:
    addr = lead["address"]
    city = lead.get("city", "")
    state = lead.get("state", "")
    score = lead.get("lead_score", 0)
    grade = lead.get("lead_grade", "B")
    priority = lead.get("priority", "WARM")

    panels = lead.get("panels_recommended", 0)
    system_kw = lead.get("system_size_kw", 0)
    sunshine = lead.get("sunshine_hours_per_year", 0)
    annual_kwh = lead.get("annual_kwh_produced", 0)
    offset = lead.get("offset_pct", 0)
    segments = lead.get("roof_segments", 0)

    monthly_bill = lead.get("monthly_bill_usd", 150)
    gross_cost = lead.get("gross_cost_usd", 0)
    itc = lead.get("federal_itc_usd", 0)
    net_cost = lead.get("net_cost_usd", 0)
    annual_savings = lead.get("annual_savings_yr1_usd", 0)
    lifetime_savings = lead.get("lifetime_savings_usd", 0)
    payback = lead.get("payback_years", 0)
    roi = lead.get("roi_25yr_pct", 0)
    co2 = lead.get("co2_offset_lbs_per_year", 0)
    trees = lead.get("trees_equivalent_per_year", 0)

    talking_pts = lead.get("talking_points", [])

    # Payment scenarios
    monthly_solar_loan = round(net_cost / (20 * 12), 0)    # 20-yr simple estimate
    monthly_savings_vs_bill = round(monthly_bill - monthly_solar_loan, 0)
    down_payment = round(net_cost * 0.1, 0)                 # 10% down
    monthly_loan_10pct = round((net_cost * 0.9) / (20 * 12), 0)
    lease_monthly = round(annual_savings / 12 * 0.55, 0)   # ~55% of savings = lease payment, rest is savings

    # Strip emoji from talking points for cleaner look in HTML
    clean_pts = []
    for pt in talking_pts:
        cleaned = re.sub(r'[\U00010000-\U0010ffff]', '', pt)
        cleaned = re.sub(r'[✅💰⚡🏛📅🌱📈]', '', cleaned).strip()
        if cleaned:
            clean_pts.append(cleaned)

    homeowner_display = homeowner_name if homeowner_name else "Your Home"
    rep_display = rep_name if rep_name else company_name
    generated_date = datetime.now().strftime("%B %d, %Y")

    # Imagery date
    img_date = lead.get("imagery_date", {})
    if isinstance(img_date, dict) and img_date.get("year"):
        img_str = f"{img_date.get('year')}"
    else:
        img_str = "Recent"

    score_pct = min(score, 100)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Solar Proposal — {addr}</title>
<style>
  /* ── Reset & base ── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', -apple-system, system-ui, sans-serif; background: #f0f4f8; color: #1a2436; line-height: 1.5; }}
  @media print {{
    body {{ background: #fff; }}
    .no-print {{ display: none !important; }}
    .page {{ box-shadow: none; margin: 0; border-radius: 0; }}
    .page-break {{ page-break-before: always; }}
  }}

  /* ── Layout ── */
  .page {{ max-width: 860px; margin: 0 auto; background: #fff; box-shadow: 0 4px 40px rgba(0,0,0,.12); }}

  /* ── Hero Header ── */
  .hero {{
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 60%, #0d5c4d 100%);
    padding: 48px 48px 40px;
    color: white;
    position: relative;
    overflow: hidden;
  }}
  .hero::before {{
    content: '☀️';
    position: absolute;
    font-size: 220px;
    right: -20px;
    top: -30px;
    opacity: 0.07;
    user-select: none;
  }}
  .hero-badge {{
    display: inline-block;
    background: rgba(251,191,36,.15);
    border: 1px solid rgba(251,191,36,.4);
    color: #fbbf24;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .1em;
    padding: 4px 14px;
    border-radius: 100px;
    margin-bottom: 20px;
  }}
  .hero h1 {{ font-size: 32px; font-weight: 800; line-height: 1.15; margin-bottom: 8px; }}
  .hero h1 span {{ color: #fbbf24; }}
  .hero-sub {{ font-size: 15px; color: rgba(255,255,255,.7); margin-bottom: 28px; }}
  .hero-address {{
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(255,255,255,.08);
    border: 1px solid rgba(255,255,255,.15);
    border-radius: 8px;
    padding: 10px 18px;
    font-size: 14px;
    color: rgba(255,255,255,.9);
  }}

  /* ── Key Numbers ── */
  .key-numbers {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0;
    border-bottom: 1px solid #e2e8f0;
  }}
  @media(max-width: 600px) {{ .key-numbers {{ grid-template-columns: repeat(2, 1fr); }} }}
  .key-num {{
    padding: 28px 20px;
    text-align: center;
    border-right: 1px solid #e2e8f0;
    background: #fff;
  }}
  .key-num:last-child {{ border-right: none; }}
  .key-num-value {{
    font-size: 36px;
    font-weight: 800;
    color: #0d5c4d;
    line-height: 1;
    margin-bottom: 6px;
  }}
  .key-num-label {{
    font-size: 12px;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: .06em;
    font-weight: 600;
  }}
  .key-num-sub {{
    font-size: 11px;
    color: #94a3b8;
    margin-top: 4px;
  }}

  /* ── Sections ── */
  .section {{ padding: 36px 48px; border-bottom: 1px solid #e2e8f0; }}
  .section:last-child {{ border-bottom: none; }}
  .section-title {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .12em;
    color: #94a3b8;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .section-title::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: #e2e8f0;
  }}

  /* ── 2-col grid ── */
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media(max-width: 600px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}

  /* ── Stat row ── */
  .stat-row {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #f1f5f9; }}
  .stat-row:last-child {{ border-bottom: none; }}
  .stat-key {{ font-size: 14px; color: #475569; }}
  .stat-val {{ font-size: 15px; font-weight: 700; color: #1a2436; }}
  .stat-val.highlight {{ color: #0d5c4d; }}

  /* ── Score ring ── */
  .score-block {{
    text-align: center;
    padding: 24px;
    background: #f8fafc;
    border-radius: 16px;
    border: 1px solid #e2e8f0;
  }}
  .score-ring {{
    width: 120px; height: 120px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    flex-direction: column;
    margin: 0 auto 16px;
    background: conic-gradient({score_color(score)} {score_pct * 3.6}deg, #e2e8f0 0deg);
    box-shadow: 0 0 0 8px #f8fafc;
  }}
  .score-inner {{
    width: 88px; height: 88px;
    border-radius: 50%;
    background: #fff;
    display: flex; align-items: center; justify-content: center;
    flex-direction: column;
    box-shadow: 0 2px 8px rgba(0,0,0,.08);
  }}
  .score-num {{ font-size: 28px; font-weight: 900; color: #1a2436; line-height: 1; }}
  .score-of {{ font-size: 11px; color: #94a3b8; }}
  .score-grade {{
    display: inline-block;
    padding: 4px 16px;
    border-radius: 100px;
    font-size: 15px;
    font-weight: 800;
    background: {'#dcfce7' if priority == 'HOT' else '#fef3c7' if priority == 'WARM' else '#dbeafe'};
    color: {'#166534' if priority == 'HOT' else '#92400e' if priority == 'WARM' else '#1e40af'};
  }}
  .score-label {{ font-size: 13px; color: #64748b; margin-top: 8px; }}

  /* ── Payment options ── */
  .payment-cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
  @media(max-width: 640px) {{ .payment-cards {{ grid-template-columns: 1fr; }} }}
  .payment-card {{
    border: 2px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    position: relative;
    transition: all .2s;
  }}
  .payment-card.featured {{
    border-color: #0d5c4d;
    background: #f0fdf4;
  }}
  .payment-card.featured::before {{
    content: '★ POPULAR';
    position: absolute;
    top: -12px; left: 50%; transform: translateX(-50%);
    background: #0d5c4d; color: white;
    font-size: 10px; font-weight: 800; letter-spacing: .08em;
    padding: 3px 12px;
    border-radius: 100px;
    white-space: nowrap;
  }}
  .payment-card h3 {{ font-size: 14px; font-weight: 700; color: #475569; margin-bottom: 12px; }}
  .payment-amount {{ font-size: 32px; font-weight: 900; color: #0d5c4d; line-height: 1; }}
  .payment-period {{ font-size: 12px; color: #94a3b8; margin-bottom: 12px; }}
  .payment-detail {{ font-size: 12px; color: #64748b; line-height: 1.6; }}
  .payment-save {{ font-size: 13px; font-weight: 700; color: #059669; margin-top: 8px; }}

  /* ── Talking points ── */
  .talking-pts {{ display: flex; flex-direction: column; gap: 10px; }}
  .talking-pt {{
    display: flex; gap: 12px; align-items: flex-start;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 3px solid #0d5c4d;
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    font-size: 14px;
    color: #334155;
    line-height: 1.5;
  }}
  .talking-pt .icon {{ font-size: 18px; flex-shrink: 0; }}

  /* ── Environmental impact ── */
  .impact-cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
  @media(max-width: 640px) {{ .impact-cards {{ grid-template-columns: 1fr; }} }}
  .impact-card {{
    text-align: center;
    padding: 20px;
    background: #f0fdf4;
    border-radius: 12px;
    border: 1px solid #bbf7d0;
  }}
  .impact-icon {{ font-size: 32px; margin-bottom: 8px; }}
  .impact-value {{ font-size: 24px; font-weight: 800; color: #166534; }}
  .impact-label {{ font-size: 12px; color: #4b7c5c; text-transform: uppercase; letter-spacing: .05em; font-weight: 600; margin-top: 4px; }}

  /* ── Footer ── */
  .footer {{
    background: #0f172a;
    color: rgba(255,255,255,.6);
    padding: 28px 48px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
    font-size: 12px;
  }}
  .footer-logo {{ color: #fbbf24; font-weight: 800; font-size: 16px; }}
  .footer-disclaimer {{ max-width: 500px; line-height: 1.6; }}

  /* ── CTA bar ── */
  .cta-bar {{
    background: linear-gradient(135deg, #059669, #0d5c4d);
    padding: 32px 48px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 24px;
    flex-wrap: wrap;
  }}
  .cta-text h2 {{ font-size: 22px; font-weight: 800; color: white; }}
  .cta-text p {{ font-size: 14px; color: rgba(255,255,255,.8); margin-top: 4px; }}
  .cta-btn {{
    display: inline-block;
    background: #fbbf24;
    color: #1a2436;
    font-weight: 800;
    font-size: 15px;
    padding: 14px 32px;
    border-radius: 8px;
    text-decoration: none;
    white-space: nowrap;
    box-shadow: 0 4px 16px rgba(0,0,0,.2);
  }}
  .no-print {{ position: fixed; top: 20px; right: 20px; display: flex; gap: 10px; z-index: 999; }}
  .no-print button {{
    background: #0f172a;
    color: white;
    border: none;
    padding: 10px 20px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 600;
    box-shadow: 0 2px 12px rgba(0,0,0,.3);
  }}
  .no-print button:hover {{ background: #1e3a5f; }}
</style>
</head>
<body>

<!-- Print / Save buttons -->
<div class="no-print">
  <button onclick="window.print()">🖨️ Print / Save PDF</button>
</div>

<div class="page">

  <!-- ── Hero ── -->
  <div class="hero">
    <div class="hero-badge">☀️ Solar Analysis Report</div>
    <h1>Your Home Could Save<br><span>{fmt_usd(annual_savings)}</span> Every Year</h1>
    <p class="hero-sub">Custom solar proposal prepared by {rep_display} • {generated_date}</p>
    <div class="hero-address">
      📍 {addr}
    </div>
  </div>

  <!-- ── Key Numbers ── -->
  <div class="key-numbers">
    <div class="key-num">
      <div class="key-num-value">{fmt_usd(annual_savings)}</div>
      <div class="key-num-label">Year 1 Savings</div>
      <div class="key-num-sub">vs. current utility bills</div>
    </div>
    <div class="key-num">
      <div class="key-num-value">{fmt_usd(lifetime_savings)}</div>
      <div class="key-num-label">25-Year Savings</div>
      <div class="key-num-sub">{fmt_num(roi, 0)}% total ROI</div>
    </div>
    <div class="key-num">
      <div class="key-num-value">{payback:.1f} yrs</div>
      <div class="key-num-label">Payback Period</div>
      <div class="key-num-sub">then free power</div>
    </div>
    <div class="key-num">
      <div class="key-num-value">{offset}%</div>
      <div class="key-num-label">Bill Offset</div>
      <div class="key-num-sub">{fmt_num(annual_kwh, 0)} kWh/yr produced</div>
    </div>
  </div>

  <!-- ── System Overview ── -->
  <div class="section">
    <div class="section-title">🔆 System Design</div>
    <div class="grid-2">
      <div>
        <div class="stat-row">
          <span class="stat-key">System Size</span>
          <span class="stat-val highlight">{system_kw} kW</span>
        </div>
        <div class="stat-row">
          <span class="stat-key">Solar Panels</span>
          <span class="stat-val">{panels} panels recommended</span>
        </div>
        <div class="stat-row">
          <span class="stat-key">Annual Production</span>
          <span class="stat-val">{fmt_num(annual_kwh, 0)} kWh</span>
        </div>
        <div class="stat-row">
          <span class="stat-key">Sunshine Hours</span>
          <span class="stat-val">{fmt_num(sunshine, 0)} hrs/year</span>
        </div>
        <div class="stat-row">
          <span class="stat-key">Roof Segments</span>
          <span class="stat-val">{segments} usable faces</span>
        </div>
        <div class="stat-row">
          <span class="stat-key">Imagery Year</span>
          <span class="stat-val">{img_str}</span>
        </div>
      </div>
      <div class="score-block">
        <div class="score-ring">
          <div class="score-inner">
            <div class="score-num">{score}</div>
            <div class="score-of">/ 100</div>
          </div>
        </div>
        <div class="score-grade">{'🔥 HOT LEAD' if priority == 'HOT' else '☀️ WARM LEAD' if priority == 'WARM' else '❄️ COOL LEAD'}</div>
        <div class="score-label">Solar Suitability Score<br>Grade: <strong>{grade}</strong> — {city}, {state}</div>
      </div>
    </div>
  </div>

  <!-- ── Financial Breakdown ── -->
  <div class="section">
    <div class="section-title">💰 Financial Breakdown</div>
    <div class="grid-2">
      <div>
        <div class="stat-row">
          <span class="stat-key">System Gross Cost</span>
          <span class="stat-val">{fmt_usd(gross_cost)}</span>
        </div>
        <div class="stat-row">
          <span class="stat-key">Federal ITC (30%)</span>
          <span class="stat-val highlight">− {fmt_usd(itc)}</span>
        </div>
        <div class="stat-row">
          <span class="stat-key">Your Net Cost</span>
          <span class="stat-val highlight">{fmt_usd(net_cost)}</span>
        </div>
        <div class="stat-row">
          <span class="stat-key">Current Monthly Bill</span>
          <span class="stat-val">{fmt_usd(monthly_bill)}/mo</span>
        </div>
        <div class="stat-row">
          <span class="stat-key">Year 1 Savings</span>
          <span class="stat-val highlight">{fmt_usd(annual_savings)}</span>
        </div>
        <div class="stat-row">
          <span class="stat-key">25-Year Lifetime Savings</span>
          <span class="stat-val highlight">{fmt_usd(lifetime_savings)}</span>
        </div>
      </div>
      <div>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:20px;">
          <div style="font-size:13px;font-weight:700;color:#475569;margin-bottom:16px;text-transform:uppercase;letter-spacing:.05em;">Savings Timeline</div>
          <!-- Simple visual bars -->
          <div style="margin-bottom:10px;">
            <div style="display:flex;justify-content:space-between;font-size:12px;color:#64748b;margin-bottom:4px;">
              <span>Year 1</span><span style="font-weight:700;color:#059669">{fmt_usd(annual_savings)}</span>
            </div>
            <div style="height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden;">
              <div style="height:100%;width:{'20' if payback < 20 else '100'}%;background:linear-gradient(90deg,#059669,#34d399);border-radius:4px;"></div>
            </div>
          </div>
          <div style="margin-bottom:10px;">
            <div style="display:flex;justify-content:space-between;font-size:12px;color:#64748b;margin-bottom:4px;">
              <span>Year 10</span><span style="font-weight:700;color:#059669">{fmt_usd(annual_savings * 10)}</span>
            </div>
            <div style="height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden;">
              <div style="height:100%;width:40%;background:linear-gradient(90deg,#059669,#34d399);border-radius:4px;"></div>
            </div>
          </div>
          <div style="margin-bottom:10px;">
            <div style="display:flex;justify-content:space-between;font-size:12px;color:#64748b;margin-bottom:4px;">
              <span>Year 25</span><span style="font-weight:700;color:#059669">{fmt_usd(lifetime_savings)}</span>
            </div>
            <div style="height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden;">
              <div style="height:100%;width:100%;background:linear-gradient(90deg,#059669,#34d399);border-radius:4px;"></div>
            </div>
          </div>
          <div style="text-align:center;margin-top:16px;padding:10px;background:#dcfce7;border-radius:8px;">
            <div style="font-size:11px;color:#4b7c5c;font-weight:700;text-transform:uppercase;">Break-Even Point</div>
            <div style="font-size:22px;font-weight:900;color:#166534;">Year {int(payback)}</div>
            <div style="font-size:11px;color:#4b7c5c;">Free power for {25 - int(payback)}+ more years</div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ── Payment Options ── -->
  <div class="section">
    <div class="section-title">💳 Financing Options</div>
    <div class="payment-cards">
      <div class="payment-card">
        <h3>💵 Cash Purchase</h3>
        <div class="payment-amount">{fmt_usd(net_cost)}</div>
        <div class="payment-period">one-time after tax credit</div>
        <div class="payment-detail">
          Best long-term ROI<br>
          Own the system outright<br>
          Full tax credit ({fmt_usd(itc)})
        </div>
        <div class="payment-save">Save {fmt_usd(lifetime_savings)} total</div>
      </div>
      <div class="payment-card featured">
        <h3>🏦 Solar Loan</h3>
        <div class="payment-amount">~{fmt_usd(monthly_solar_loan)}</div>
        <div class="payment-period">/month (20-yr est.)</div>
        <div class="payment-detail">
          $0 down available<br>
          Own the system<br>
          Still get 30% ITC
        </div>
        <div class="payment-save">Save {fmt_usd(max(0, monthly_savings_vs_bill * 12))} vs bill/yr</div>
      </div>
      <div class="payment-card">
        <h3>📋 Solar Lease</h3>
        <div class="payment-amount">~{fmt_usd(lease_monthly)}</div>
        <div class="payment-period">/month est.</div>
        <div class="payment-detail">
          $0 down<br>
          Maintenance included<br>
          Immediate savings
        </div>
        <div class="payment-save">Locked low rate, no risk</div>
      </div>
    </div>
    <p style="font-size:11px;color:#94a3b8;margin-top:16px;text-align:center;">* Payment estimates are illustrative. Final terms depend on lender, credit, and system configuration.</p>
  </div>

  <!-- ── Why This Home ── -->
  {'<div class="section"><div class="section-title">📋 Why This Home is a Great Fit</div><div class="talking-pts">' + ''.join(f'<div class="talking-pt"><span class="icon">✓</span><span>{pt}</span></div>' for pt in clean_pts[:5]) + '</div></div>' if clean_pts else ''}

  <!-- ── Environmental Impact ── -->
  <div class="section">
    <div class="section-title">🌱 Environmental Impact</div>
    <div class="impact-cards">
      <div class="impact-card">
        <div class="impact-icon">🌍</div>
        <div class="impact-value">{fmt_num(co2 / 2000, 1)}T</div>
        <div class="impact-label">CO₂ Offset / Year</div>
      </div>
      <div class="impact-card">
        <div class="impact-icon">🌳</div>
        <div class="impact-value">{fmt_num(trees, 0)}</div>
        <div class="impact-label">Trees Equivalent / Year</div>
      </div>
      <div class="impact-card">
        <div class="impact-icon">⚡</div>
        <div class="impact-value">{fmt_num(annual_kwh, 0)}</div>
        <div class="impact-label">Clean kWh Produced / Year</div>
      </div>
    </div>
  </div>

  <!-- ── CTA ── -->
  <div class="cta-bar">
    <div class="cta-text">
      <h2>Ready to Lock In Your Savings?</h2>
      <p>Schedule a free site assessment — takes 30 minutes, zero obligation.</p>
    </div>
    <a href="tel:+1-800-SOLAR" class="cta-btn">📞 Schedule Now</a>
  </div>

  <!-- ── Footer ── -->
  <div class="footer">
    <div>
      <div class="footer-logo">☀️ {company_name}</div>
      <div style="margin-top:4px;">Prepared for: {homeowner_display}</div>
      <div>Generated: {generated_date}</div>
    </div>
    <div class="footer-disclaimer">
      Projections are estimates based on satellite solar data (Google Solar API), local utility rates, and federal incentive rates as of {generated_date}. 
      Actual savings may vary. Federal ITC of 30% applies to systems installed through 2032. 
      Consult a tax professional for your specific situation.
    </div>
  </div>

</div>

</body>
</html>"""

    return html


# ── CLI main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a beautiful HTML solar proposal for a homeowner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/generate_proposal.py "1905 E Marquette Dr, Gilbert AZ 85234"
  python scripts/generate_proposal.py "address" --bill 195 --name "The Garcia Family" --rep "Jake Torres"
  python scripts/generate_proposal.py "address" --bill 225 --output /tmp/my_proposal.html
  python scripts/generate_proposal.py "address" --print-path   # just print file path (for piping/open)
"""
    )
    parser.add_argument("address", help="Full street address")
    parser.add_argument("--bill", type=float, default=150.0, help="Monthly electric bill (default: 150)")
    parser.add_argument("--rate", type=float, default=0.14, help="Utility rate $/kWh (default: 0.14)")
    parser.add_argument("--name", default="", help="Homeowner name (e.g., 'The Garcia Family')")
    parser.add_argument("--rep", default="", help="Rep name to show on proposal")
    parser.add_argument("--company", default="Elevate Solar", help="Company name (default: Elevate Solar)")
    parser.add_argument("--output", default="", help="Output file path (default: auto in cache/proposals/)")
    parser.add_argument("--print-path", action="store_true", help="Print output path to stdout (for scripting)")
    parser.add_argument("--open", action="store_true", help="Open in browser after generating")
    parser.add_argument("--json-lead", action="store_true", help="Also print lead JSON to stderr")
    args = parser.parse_args()

    print(f"🔍 Enriching: {args.address} (bill=${args.bill}/mo)...", file=sys.stderr)
    lead = enrich_lead(args.address, monthly_bill=args.bill, utility_rate=args.rate)

    if "error" in lead:
        print(f"❌ Error: {lead['error']}", file=sys.stderr)
        sys.exit(1)

    if args.json_lead:
        print(json.dumps(lead, indent=2), file=sys.stderr)

    print(f"✅ {lead['address']} — Score: {lead['lead_score']}/100 {lead.get('priority', '')} ({lead.get('lead_grade', '')})", file=sys.stderr)

    # Render HTML
    html = render_proposal(lead, homeowner_name=args.name, rep_name=args.rep, company_name=args.company)

    # Output path
    if args.output:
        out_path = Path(args.output)
    else:
        proposals_dir = Path("/root/solar-tools/cache/proposals")
        proposals_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r'[^a-z0-9]+', '_', lead['address'].lower())[:60]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = proposals_dir / f"proposal_{slug}_{timestamp}.html"

    out_path.write_text(html, encoding="utf-8")

    print(f"📄 Proposal saved: {out_path}", file=sys.stderr)
    print(f"   → {lead.get('annual_savings_yr1_usd', 0):,.0f}/yr savings | {lead.get('payback_years', 0):.1f}yr payback | {lead.get('lifetime_savings_usd', 0):,.0f} lifetime", file=sys.stderr)

    if args.print_path:
        print(str(out_path))
    else:
        print(f"\n✨ Open in browser: file://{out_path}", file=sys.stderr)

    if args.open:
        os.system(f"xdg-open file://{out_path} 2>/dev/null || open file://{out_path} 2>/dev/null || echo 'Cannot auto-open browser'")


if __name__ == "__main__":
    main()
