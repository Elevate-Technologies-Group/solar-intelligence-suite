#!/usr/bin/env python3
"""
Territory Intelligence Report Generator
Produces a beautiful, standalone HTML briefing for any ZIP code.
Can pull from cached territory scans or run a live scan.

Usage:
    python scripts/generate_territory_report.py 85234
    python scripts/generate_territory_report.py 85234 --bill 195
    python scripts/generate_territory_report.py 85234 --live       # force fresh scan
    python scripts/generate_territory_report.py 85234 --print-path # just output file path
    python scripts/generate_territory_report.py 85234 --open       # open in browser

Output:
    cache/territory_reports/territory_<zip>_<timestamp>.html
"""

import sys, os, json, argparse, math
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CACHE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "cache"
REPORTS_DIR = CACHE_DIR / "territory_reports"

# ─── Data Loading ─────────────────────────────────────────────────────────────

def load_territory_from_cache(zip_code: str) -> dict | None:
    """Load territory data from cache file if available."""
    cache_file = CACHE_DIR / f"territory_{zip_code}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)
    return None


def run_live_scan(zip_code: str, monthly_bill: float = 175, sample: int = 5) -> dict:
    """Run a fresh territory scan via the tools module."""
    from tools.territory import scan_territory
    result = scan_territory(zip_code, monthly_bill=monthly_bill, sample=sample)
    return result


def get_territory_data(zip_code: str, live: bool = False, monthly_bill: float = 175) -> dict:
    """Get territory data from cache or live scan."""
    if not live:
        data = load_territory_from_cache(zip_code)
        if data:
            return data
    return run_live_scan(zip_code, monthly_bill=monthly_bill)


# ─── Score Bar ────────────────────────────────────────────────────────────────

def score_bar_html(score: float, width: int = 200) -> str:
    """Generate an inline SVG score bar."""
    pct = min(100, max(0, score))
    if pct >= 80:
        color = "#22c55e"
    elif pct >= 60:
        color = "#f59e0b"
    elif pct >= 40:
        color = "#fb923c"
    else:
        color = "#ef4444"
    filled = int(width * pct / 100)
    return f"""<svg width="{width}" height="10" style="border-radius:5px;overflow:hidden;vertical-align:middle">
  <rect width="{width}" height="10" fill="#1e293b"/>
  <rect width="{filled}" height="10" fill="{color}"/>
</svg>"""


def priority_badge(priority: str) -> str:
    colors = {
        "HOT":  ("#dc2626", "#fef2f2"),
        "WARM": ("#d97706", "#fffbeb"),
        "COOL": ("#2563eb", "#eff6ff"),
        "LOW":  ("#6b7280", "#f9fafb"),
    }
    bg, fg = colors.get(priority, ("#6b7280", "#f9fafb"))
    icons = {"HOT": "🔥", "WARM": "☀️", "COOL": "❄️", "LOW": "📉"}
    icon = icons.get(priority, "")
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:20px;'
            f'background:{fg};color:{bg};font-weight:700;font-size:12px;border:1px solid {bg}20">'
            f'{icon} {priority}</span>')


def grade_ring_svg(score: float, grade: str, size: int = 80) -> str:
    """Conic-gradient score ring."""
    pct = min(100, max(0, score))
    if pct >= 80:
        color = "#22c55e"
    elif pct >= 60:
        color = "#f59e0b"
    elif pct >= 40:
        color = "#fb923c"
    else:
        color = "#ef4444"
    deg = int(pct * 3.6)
    return f"""<div style="width:{size}px;height:{size}px;border-radius:50%;
        background:conic-gradient({color} {deg}deg, #1e293b {deg}deg);
        display:flex;align-items:center;justify-content:center;position:relative">
      <div style="width:{size-14}px;height:{size-14}px;border-radius:50%;
          background:#0f172a;display:flex;flex-direction:column;
          align-items:center;justify-content:center">
        <span style="color:{color};font-weight:800;font-size:{max(14, size//5)}px;line-height:1">{int(score)}</span>
        <span style="color:#94a3b8;font-size:{max(9, size//8)}px;font-weight:600">{grade}</span>
      </div>
    </div>"""


# ─── HTML Generation ──────────────────────────────────────────────────────────

def clean_talking_point(tp: str) -> str:
    """Strip emoji prefixes from talking points."""
    import re
    # Remove leading emoji + space
    return re.sub(r'^[\U00010000-\U0010ffff\u2600-\u26FF\u2700-\u27BF✅💰⚡🏛️📅🌱📈☀️🔥❄️]+\s*', '', tp)


def format_currency(val, decimals: int = 0) -> str:
    if val is None: return "N/A"
    if decimals:
        return f"${val:,.{decimals}f}"
    return f"${int(val):,}"


def format_num(val, decimals: int = 1) -> str:
    if val is None: return "N/A"
    return f"{val:,.{decimals}f}"


def imagery_year(d) -> str:
    if isinstance(d, dict): return str(d.get("year", "N/A"))
    return str(d) if d else "N/A"


def generate_territory_report_html(data: dict, zip_code: str, generated_by: str = "Elevate Solar") -> str:
    """Render the complete HTML territory report."""
    now = datetime.now()
    prospects = data.get("prospects", [])
    center_label = data.get("center", f"ZIP {zip_code}")
    city_state = center_label.replace(f", {zip_code}, USA", "").replace(", USA", "")
    territory_grade = data.get("territory_grade", "UNKNOWN")
    avg_score = data.get("avg_lead_score", 0)
    hot_leads = data.get("hot_leads", 0)
    total_leads = data.get("leads_enriched", len(prospects))
    avg_savings = data.get("avg_annual_savings_usd", 0)
    avg_payback = data.get("avg_payback_years", 0)
    addresses_scanned = data.get("addresses_scanned", total_leads)

    # Aggregate stats from prospects
    warm_leads = sum(1 for p in prospects if p.get("priority") == "WARM")
    cool_leads = sum(1 for p in prospects if p.get("priority") == "COOL")
    low_leads = sum(1 for p in prospects if p.get("priority") == "LOW")
    total_pipeline = sum(p.get("annual_savings_yr1_usd", 0) for p in prospects if p.get("priority") in ("HOT","WARM"))
    avg_sunshine = 0
    if prospects:
        avg_sunshine = sum(p.get("sunshine_hours_per_year", 0) for p in prospects) / len(prospects)
    avg_offset = 0
    if prospects:
        avg_offset = sum(p.get("offset_pct", 0) for p in prospects) / len(prospects)
    total_co2 = sum(p.get("co2_offset_lbs_per_year", 0) for p in prospects)
    total_trees = sum(p.get("trees_equivalent_per_year", 0) for p in prospects)
    avg_net_cost = 0
    if prospects:
        avg_net_cost = sum(p.get("net_cost_usd", 0) for p in prospects) / len(prospects)
    avg_roi = 0
    if prospects:
        avg_roi = sum(p.get("roi_25yr_pct", 0) for p in prospects) / len(prospects)

    # Color theme based on grade
    grade_themes = {
        "HOT":  ("from-red-900", "#dc2626", "#fca5a5", "🔥"),
        "WARM": ("from-amber-900", "#d97706", "#fcd34d", "☀️"),
        "COOL": ("from-blue-900", "#2563eb", "#93c5fd", "❄️"),
        "LOW":  ("from-slate-900", "#6b7280", "#d1d5db", "📉"),
    }
    _, accent, light, grade_icon = grade_themes.get(territory_grade, grade_themes["COOL"])

    # Sort prospects by score descending
    prospects_sorted = sorted(prospects, key=lambda x: x.get("lead_score", 0), reverse=True)

    # ── Lead cards HTML ──────────────────────────────────────────────────────
    lead_cards_html = ""
    for i, p in enumerate(prospects_sorted):
        score = p.get("lead_score", 0)
        grade = p.get("lead_grade", "?")
        prio = p.get("priority", "COOL")
        addr = p.get("address", "Unknown").replace(", USA", "")
        short_addr = addr.split(",")[0]
        city_part = ", ".join(addr.split(",")[1:]).strip()

        panels = p.get("panels_recommended", 0)
        kw = p.get("system_size_kw", 0)
        savings = p.get("annual_savings_yr1_usd", 0)
        payback = p.get("payback_years", 0)
        net_cost = p.get("net_cost_usd", 0)
        itc = p.get("federal_itc_usd", 0)
        gross = p.get("gross_cost_usd", 0)
        offset = p.get("offset_pct", 0)
        sunshine = p.get("sunshine_hours_per_year", 0)
        roi = p.get("roi_25yr_pct", 0)
        lifetime = p.get("lifetime_savings_usd", 0)
        segments = p.get("roof_segments", 0)
        img_yr = imagery_year(p.get("imagery_date"))
        co2 = p.get("co2_offset_lbs_per_year", 0)
        trees = p.get("trees_equivalent_per_year", 0)

        tps = p.get("talking_points", [])[:4]

        prio_colors = {
            "HOT": ("#dc2626", "#fef2f2", "#fee2e2"),
            "WARM": ("#d97706", "#fffbeb", "#fef3c7"),
            "COOL": ("#2563eb", "#eff6ff", "#dbeafe"),
            "LOW": ("#6b7280", "#f9fafb", "#f3f4f6"),
        }
        ac, bg_light, bg_pale = prio_colors.get(prio, prio_colors["COOL"])

        rank_icons = ["🥇", "🥈", "🥉"]
        rank_icon = rank_icons[i] if i < 3 else f"#{i+1}"

        lead_cards_html += f"""
        <div class="lead-card" style="background:#1e293b;border-radius:12px;padding:24px;
             border:2px solid {ac}30;margin-bottom:20px;page-break-inside:avoid">
          <div style="display:flex;align-items:flex-start;gap:20px;flex-wrap:wrap">

            <!-- Score Ring -->
            <div style="flex-shrink:0">
              {grade_ring_svg(score, grade, size=72)}
              <div style="text-align:center;margin-top:6px;color:#64748b;font-size:11px">SCORE</div>
            </div>

            <!-- Address + Badge -->
            <div style="flex:1;min-width:200px">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
                <span style="font-size:20px">{rank_icon}</span>
                {priority_badge(prio)}
              </div>
              <div style="color:#f1f5f9;font-size:17px;font-weight:700">{short_addr}</div>
              <div style="color:#94a3b8;font-size:13px">{city_part}</div>
              <div style="margin-top:8px">{score_bar_html(score, 180)}</div>
            </div>

            <!-- Key Stats Grid -->
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;flex:2;min-width:300px">
              <div style="background:#0f172a;border-radius:8px;padding:10px;text-align:center">
                <div style="color:{ac};font-size:18px;font-weight:700">{format_currency(savings)}</div>
                <div style="color:#94a3b8;font-size:10px">Yr 1 Savings</div>
              </div>
              <div style="background:#0f172a;border-radius:8px;padding:10px;text-align:center">
                <div style="color:#38bdf8;font-size:18px;font-weight:700">{format_num(payback, 1)}yr</div>
                <div style="color:#94a3b8;font-size:10px">Payback</div>
              </div>
              <div style="background:#0f172a;border-radius:8px;padding:10px;text-align:center">
                <div style="color:#a78bfa;font-size:18px;font-weight:700">{panels}p / {kw}kW</div>
                <div style="color:#94a3b8;font-size:10px">System Size</div>
              </div>
              <div style="background:#0f172a;border-radius:8px;padding:10px;text-align:center">
                <div style="color:#f59e0b;font-size:18px;font-weight:700">{format_currency(net_cost)}</div>
                <div style="color:#94a3b8;font-size:10px">Net Cost (post-ITC)</div>
              </div>
              <div style="background:#0f172a;border-radius:8px;padding:10px;text-align:center">
                <div style="color:#22c55e;font-size:18px;font-weight:700">{int(offset)}%</div>
                <div style="color:#94a3b8;font-size:10px">Energy Offset</div>
              </div>
              <div style="background:#0f172a;border-radius:8px;padding:10px;text-align:center">
                <div style="color:#e879f9;font-size:18px;font-weight:700">{int(roi)}%</div>
                <div style="color:#94a3b8;font-size:10px">25yr ROI</div>
              </div>
            </div>
          </div>

          <!-- Additional Details Row -->
          <div style="display:flex;gap:20px;margin-top:16px;flex-wrap:wrap;font-size:12px;color:#64748b">
            <span>☀️ {int(sunshine):,} hr sunshine/yr</span>
            <span>🏠 {segments} roof segments</span>
            <span>📅 Imagery: {img_yr}</span>
            <span>💰 Gross: {format_currency(gross)} → ITC {format_currency(itc)} → Net {format_currency(net_cost)}</span>
            <span>📈 Lifetime: {format_currency(lifetime)}</span>
            <span>🌱 {int(co2/2000*10)/10} tons CO₂/yr = {int(trees)} trees</span>
          </div>

          <!-- Talking Points -->
          <div style="margin-top:14px">
            <div style="color:#475569;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">
              Rep Talking Points
            </div>
            <ul style="margin:0;padding-left:16px;color:#94a3b8;font-size:12px;line-height:1.7">
              {''.join(f"<li>{clean_talking_point(tp)}</li>" for tp in tps)}
            </ul>
          </div>
        </div>
"""

    # ── Priority breakdown bar ────────────────────────────────────────────────
    pbar_total = max(total_leads, 1)
    hot_pct = int(hot_leads / pbar_total * 100)
    warm_pct = int(warm_leads / pbar_total * 100)
    cool_pct = int(cool_leads / pbar_total * 100)
    low_pct = max(0, 100 - hot_pct - warm_pct - cool_pct)

    priority_bar = f"""
    <div style="display:flex;height:16px;border-radius:8px;overflow:hidden;margin:12px 0">
      <div style="width:{hot_pct}%;background:#dc2626" title="HOT: {hot_leads}"></div>
      <div style="width:{warm_pct}%;background:#f59e0b" title="WARM: {warm_leads}"></div>
      <div style="width:{cool_pct}%;background:#3b82f6" title="COOL: {cool_leads}"></div>
      <div style="width:{low_pct}%;background:#374151" title="LOW: {low_leads}"></div>
    </div>
    <div style="display:flex;gap:16px;font-size:11px;color:#64748b">
      <span><span style="color:#dc2626">●</span> HOT: {hot_leads}</span>
      <span><span style="color:#f59e0b">●</span> WARM: {warm_leads}</span>
      <span><span style="color:#3b82f6">●</span> COOL: {cool_leads}</span>
      <span><span style="color:#374151">●</span> LOW: {low_leads}</span>
    </div>"""

    # ── Score breakdown chart ─────────────────────────────────────────────────
    score_dist_rows = ""
    if prospects_sorted:
        for p in prospects_sorted:
            s = p.get("lead_score", 0)
            sc = p.get("score_breakdown", {})
            addr_short = p.get("address", "").split(",")[0]
            score_dist_rows += f"""<tr>
              <td style="color:#94a3b8;font-size:12px;padding:6px 8px">{addr_short}</td>
              <td style="padding:6px 8px">{priority_badge(p.get('priority','COOL'))}</td>
              <td style="color:#22c55e;font-size:12px;padding:6px 8px;text-align:center">{sc.get('sunshine',0)}</td>
              <td style="color:#a78bfa;font-size:12px;padding:6px 8px;text-align:center">{sc.get('roof_quality',0)}</td>
              <td style="color:#f59e0b;font-size:12px;padding:6px 8px;text-align:center">{sc.get('monthly_bill',0)}</td>
              <td style="color:#38bdf8;font-size:12px;padding:6px 8px;text-align:center">{sc.get('payback',0)}</td>
              <td style="color:#e879f9;font-size:12px;padding:6px 8px;text-align:center">{sc.get('roi',0)}</td>
              <td style="font-weight:700;font-size:14px;padding:6px 8px;text-align:center;color:{accent}">{s}</td>
            </tr>"""

    # ── Full HTML ─────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Territory Intelligence Report — ZIP {zip_code} | {generated_by}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      line-height: 1.5;
    }}
    @media print {{
      body {{ background: #fff; color: #111; }}
      .no-print {{ display: none !important; }}
      .lead-card {{ border: 1px solid #ddd !important; background: #f9fafb !important; color: #111 !important; }}
    }}
    table {{ border-collapse: collapse; width: 100%; }}
    th {{ background: #0f172a; color: #64748b; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; padding: 8px; }}
    tr:nth-child(even) {{ background: #162032; }}
    a {{ color: {accent}; text-decoration: none; }}
  </style>
</head>
<body>

<!-- ── HEADER ─────────────────────────────────────────────────────────────── -->
<div style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);
     border-bottom:3px solid {accent};padding:32px 40px">
  <div style="max-width:1100px;margin:0 auto">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px">
      <div>
        <div style="color:{light};font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase">
          {grade_icon} Territory Intelligence Report
        </div>
        <h1 style="color:#f8fafc;font-size:32px;font-weight:800;margin-top:4px">
          {city_state}
        </h1>
        <div style="color:#94a3b8;font-size:15px;margin-top:4px">
          ZIP Code: <strong style="color:{light}">{zip_code}</strong> &nbsp;·&nbsp;
          Generated: {now.strftime("%B %d, %Y at %I:%M %p")} &nbsp;·&nbsp;
          By: {generated_by}
        </div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:center">
        {grade_ring_svg(avg_score, territory_grade, size=96)}
        <div style="color:#64748b;font-size:11px;margin-top:4px">TERRITORY SCORE</div>
      </div>
    </div>
  </div>
</div>

<!-- ── PRINT BUTTON ────────────────────────────────────────────────────────── -->
<div class="no-print" style="text-align:right;padding:12px 40px;background:#1e293b;
     border-bottom:1px solid #334155">
  <button onclick="window.print()" style="background:{accent};color:#fff;border:none;
       padding:8px 20px;border-radius:6px;cursor:pointer;font-weight:600;font-size:13px">
    🖨️ Print / Save PDF
  </button>
</div>

<div style="max-width:1100px;margin:0 auto;padding:32px 24px">

  <!-- ── KPI ROW ──────────────────────────────────────────────────────────── -->
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin-bottom:32px">
    <div style="background:#1e293b;border-radius:12px;padding:20px;text-align:center;border-top:3px solid {accent}">
      <div style="color:{accent};font-size:28px;font-weight:800">{hot_leads}</div>
      <div style="color:#64748b;font-size:12px;font-weight:600;text-transform:uppercase">🔥 HOT Leads</div>
    </div>
    <div style="background:#1e293b;border-radius:12px;padding:20px;text-align:center;border-top:3px solid #f59e0b">
      <div style="color:#f59e0b;font-size:28px;font-weight:800">{warm_leads}</div>
      <div style="color:#64748b;font-size:12px;font-weight:600;text-transform:uppercase">☀️ WARM Leads</div>
    </div>
    <div style="background:#1e293b;border-radius:12px;padding:20px;text-align:center;border-top:3px solid #22c55e">
      <div style="color:#22c55e;font-size:28px;font-weight:800">{format_currency(avg_savings)}</div>
      <div style="color:#64748b;font-size:12px;font-weight:600;text-transform:uppercase">Avg Yr1 Savings</div>
    </div>
    <div style="background:#1e293b;border-radius:12px;padding:20px;text-align:center;border-top:3px solid #38bdf8">
      <div style="color:#38bdf8;font-size:28px;font-weight:800">{format_num(avg_payback, 1)}yr</div>
      <div style="color:#64748b;font-size:12px;font-weight:600;text-transform:uppercase">Avg Payback</div>
    </div>
    <div style="background:#1e293b;border-radius:12px;padding:20px;text-align:center;border-top:3px solid #a78bfa">
      <div style="color:#a78bfa;font-size:28px;font-weight:800">{format_currency(total_pipeline)}</div>
      <div style="color:#64748b;font-size:12px;font-weight:600;text-transform:uppercase">Pipeline / Yr</div>
    </div>
    <div style="background:#1e293b;border-radius:12px;padding:20px;text-align:center;border-top:3px solid #e879f9">
      <div style="color:#e879f9;font-size:28px;font-weight:800">{total_leads}</div>
      <div style="color:#64748b;font-size:12px;font-weight:600;text-transform:uppercase">Leads Analyzed</div>
    </div>
  </div>

  <!-- ── TERRITORY OVERVIEW ──────────────────────────────────────────────── -->
  <div style="background:#1e293b;border-radius:12px;padding:24px;margin-bottom:28px">
    <h2 style="color:#f1f5f9;font-size:18px;font-weight:700;margin-bottom:16px">📊 Territory Overview</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;flex-wrap:wrap">
      <div>
        <div style="color:#64748b;font-size:12px;margin-bottom:4px">Lead Priority Breakdown</div>
        {priority_bar}
        <div style="margin-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div style="background:#0f172a;border-radius:8px;padding:12px">
            <div style="color:#94a3b8;font-size:11px">Avg Sunshine Hours</div>
            <div style="color:#fbbf24;font-size:18px;font-weight:700">{int(avg_sunshine):,} hr/yr</div>
          </div>
          <div style="background:#0f172a;border-radius:8px;padding:12px">
            <div style="color:#94a3b8;font-size:11px">Avg Energy Offset</div>
            <div style="color:#22c55e;font-size:18px;font-weight:700">{int(avg_offset)}%</div>
          </div>
          <div style="background:#0f172a;border-radius:8px;padding:12px">
            <div style="color:#94a3b8;font-size:11px">Avg Net System Cost</div>
            <div style="color:#f59e0b;font-size:18px;font-weight:700">{format_currency(avg_net_cost)}</div>
          </div>
          <div style="background:#0f172a;border-radius:8px;padding:12px">
            <div style="color:#94a3b8;font-size:11px">Avg 25yr ROI</div>
            <div style="color:#e879f9;font-size:18px;font-weight:700">{int(avg_roi)}%</div>
          </div>
        </div>
      </div>
      <div>
        <div style="color:#64748b;font-size:12px;margin-bottom:8px">Environmental Impact (Territory Total)</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div style="background:#0f172a;border-radius:8px;padding:12px">
            <div style="color:#94a3b8;font-size:11px">Total CO₂ Offset/yr</div>
            <div style="color:#34d399;font-size:18px;font-weight:700">{total_co2/2000:.1f} tons</div>
          </div>
          <div style="background:#0f172a;border-radius:8px;padding:12px">
            <div style="color:#94a3b8;font-size:11px">Trees Equivalent/yr</div>
            <div style="color:#4ade80;font-size:18px;font-weight:700">{int(total_trees):,} 🌱</div>
          </div>
          <div style="background:#0f172a;border-radius:8px;padding:12px">
            <div style="color:#94a3b8;font-size:11px">Addresses Scanned</div>
            <div style="color:#38bdf8;font-size:18px;font-weight:700">{addresses_scanned}</div>
          </div>
          <div style="background:#0f172a;border-radius:8px;padding:12px">
            <div style="color:#94a3b8;font-size:11px">Territory Grade</div>
            <div style="font-size:18px;font-weight:700">{priority_badge(territory_grade)}</div>
          </div>
        </div>
        <div style="margin-top:12px;padding:12px;background:#0f172a;border-radius:8px;
             border-left:3px solid {accent}">
          <div style="color:#94a3b8;font-size:11px">💡 Sales Manager Note</div>
          <div style="color:#cbd5e1;font-size:13px;margin-top:4px">
            {"This territory is primed for canvassing — " + str(hot_leads) + " HOT leads with avg " + str(int(avg_savings)) + "/yr savings per install. " if hot_leads >= 3 else ""}
            {"Average " + format_num(avg_payback, 1) + "-year payback is an easy close. " if avg_payback and avg_payback < 10 else ""}
            Focus on HOT leads first — they convert at highest rates. Use the talking points below per door.
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ── SCORE BREAKDOWN TABLE ──────────────────────────────────────────── -->
  <div style="background:#1e293b;border-radius:12px;padding:24px;margin-bottom:28px;overflow-x:auto">
    <h2 style="color:#f1f5f9;font-size:18px;font-weight:700;margin-bottom:16px">🎯 Lead Score Breakdown</h2>
    <table>
      <thead>
        <tr>
          <th style="text-align:left">Address</th>
          <th>Priority</th>
          <th style="color:#22c55e">Sunshine</th>
          <th style="color:#a78bfa">Roof</th>
          <th style="color:#f59e0b">Bill</th>
          <th style="color:#38bdf8">Payback</th>
          <th style="color:#e879f9">ROI</th>
          <th style="color:{accent}">Total</th>
        </tr>
      </thead>
      <tbody>
        {score_dist_rows}
      </tbody>
    </table>
    <div style="margin-top:10px;color:#475569;font-size:11px">
      Max possible: Sunshine 25 + Roof 15 + Bill 20 + Payback 20 + ROI 10 + bonuses = 110 pts
    </div>
  </div>

  <!-- ── LEAD CARDS ─────────────────────────────────────────────────────── -->
  <h2 style="color:#f1f5f9;font-size:18px;font-weight:700;margin-bottom:20px">
    🏠 Top Prospects ({len(prospects_sorted)} Leads)
  </h2>
  {lead_cards_html if lead_cards_html else '<div style="color:#64748b;padding:20px">No prospects in this territory yet. Run a live scan to populate.</div>'}

  <!-- ── FOOTER ────────────────────────────────────────────────────────────── -->
  <div style="margin-top:40px;padding-top:24px;border-top:1px solid #1e293b;
       color:#475569;font-size:11px;text-align:center">
    <p>Generated by {generated_by} Solar Intelligence Suite · {now.strftime("%B %d, %Y")} · ZIP {zip_code}</p>
    <p style="margin-top:4px">Data sourced from Google Solar API. Estimates based on {int(175)} $/mo avg bill. Actual savings vary by utility rate, usage, and system configuration.</p>
    <p style="margin-top:4px">⚡ Powered by Elevate Technologies — <a href="http://localhost:8765">Solar Intelligence Suite v1.0</a></p>
  </div>

</div>
</body>
</html>"""

    return html


def save_report(html: str, zip_code: str) -> Path:
    """Save report to cache/territory_reports/ and return path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"territory_{zip_code}_{timestamp}.html"
    path.write_text(html, encoding="utf-8")
    return path


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a Territory Intelligence Report for any ZIP code"
    )
    parser.add_argument("zip_code", help="ZIP code to report on (e.g. 85234)")
    parser.add_argument("--bill", type=float, default=175.0, help="Assumed monthly bill (default: $175)")
    parser.add_argument("--live", action="store_true", help="Force fresh scan (ignore cache)")
    parser.add_argument("--company", default="Elevate Solar", help="Company name on report")
    parser.add_argument("--print-path", action="store_true", help="Only print saved file path")
    parser.add_argument("--open", action="store_true", help="Open report in browser after generating")
    parser.add_argument("--no-color", action="store_true", help="Suppress ANSI output (not applicable to HTML)")

    args = parser.parse_args()

    print(f"📊 Territory Intelligence Report — ZIP {args.zip_code}")
    print(f"   Loading data {'(live scan)' if args.live else '(from cache)'}...")

    data = get_territory_data(args.zip_code, live=args.live, monthly_bill=args.bill)

    if not data:
        print(f"❌ No data available for ZIP {args.zip_code}. Try --live to force a scan.")
        sys.exit(1)

    leads_count = len(data.get("prospects", []))
    print(f"   ✅ {leads_count} leads loaded — generating HTML report...")

    html = generate_territory_report_html(data, args.zip_code, generated_by=args.company)
    path = save_report(html, args.zip_code)

    if args.print_path:
        print(str(path))
        return

    file_size_kb = path.stat().st_size // 1024
    print(f"\n✅ Report generated!")
    print(f"   📄 File: {path}")
    print(f"   📦 Size: {file_size_kb} KB")
    print(f"   🏠 Leads: {leads_count}")
    print(f"   🔥 HOT: {data.get('hot_leads', 0)}")
    print(f"   📈 Avg Score: {data.get('avg_lead_score', 0):.1f}/100")
    print(f"   💰 Avg Savings: ${data.get('avg_annual_savings_usd', 0):,}/yr")
    print(f"\n   Open in browser: file://{path}")

    if args.open:
        import webbrowser
        webbrowser.open(f"file://{path}")


if __name__ == "__main__":
    main()
