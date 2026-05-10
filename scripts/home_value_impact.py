#!/usr/bin/env python3
"""
Home Value & Solar Equity Impact Report
========================================
Shows how solar increases a home's resale value — powerful closing tool.

Key data sources:
  - Zillow/NREL research: solar adds ~4% to home value on average
  - Lawrence Berkeley National Lab "Sold Premium" study: $15/W premium in US
  - AZ-specific median home values by zip code (2024 estimates)

Usage:
  python scripts/home_value_impact.py "1905 E Marquette Dr, Gilbert, AZ" --bill 175
  python scripts/home_value_impact.py --zip 85234 --bill 175
  python scripts/home_value_impact.py --zip 85254 --bill 200 --no-color
  python scripts/home_value_impact.py --zip 85001 --json
"""

import sys, os, json, argparse, re
from datetime import datetime

# Ensure project root in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─────────────────────────────────────────────
# AZ ZIP CODE MEDIAN HOME VALUES (2024 estimates)
# Source: Zillow Research / US Census ACS 2023
# ─────────────────────────────────────────────
AZ_ZIP_HOME_VALUES = {
    # Scottsdale
    "85250": 950000, "85251": 620000, "85252": 550000, "85253": 1100000,
    "85254": 800000, "85255": 1050000, "85256": 580000, "85257": 490000,
    "85258": 750000, "85259": 820000, "85260": 680000, "85262": 900000,
    "85266": 780000, "85268": 700000,
    # Gilbert
    "85233": 480000, "85234": 510000, "85295": 530000, "85296": 545000,
    "85297": 520000, "85298": 560000,
    # Chandler
    "85224": 465000, "85225": 450000, "85226": 440000, "85244": 470000,
    "85246": 480000, "85248": 520000, "85249": 530000,
    # Mesa
    "85201": 380000, "85202": 370000, "85203": 385000, "85204": 360000,
    "85205": 400000, "85206": 410000, "85207": 420000, "85208": 390000,
    "85209": 430000, "85210": 375000, "85212": 460000, "85213": 440000,
    "85215": 480000, "85216": 390000,
    # Tempe
    "85281": 420000, "85282": 410000, "85283": 430000, "85284": 460000,
    "85285": 440000, "85287": 400000,
    # Phoenix core
    "85001": 350000, "85002": 310000, "85003": 380000, "85004": 400000,
    "85006": 340000, "85007": 300000, "85008": 360000, "85009": 290000,
    "85010": 330000, "85012": 370000, "85013": 390000, "85014": 420000,
    "85015": 330000, "85016": 440000, "85017": 300000, "85018": 480000,
    "85019": 295000, "85020": 420000, "85021": 380000, "85022": 400000,
    "85023": 360000, "85024": 370000, "85027": 350000, "85028": 480000,
    "85029": 330000, "85031": 295000, "85032": 430000, "85033": 310000,
    "85034": 280000, "85035": 290000, "85037": 330000, "85040": 360000,
    "85041": 370000, "85042": 380000, "85043": 350000, "85044": 420000,
    "85045": 450000, "85048": 480000, "85050": 470000, "85051": 340000,
    "85053": 350000, "85054": 430000, "85083": 420000, "85085": 460000,
    "85086": 470000,
    # Glendale
    "85301": 330000, "85302": 320000, "85303": 310000, "85304": 335000,
    "85305": 340000, "85306": 360000, "85307": 330000, "85308": 380000,
    "85309": 335000, "85310": 400000,
    # Peoria
    "85345": 370000, "85380": 390000, "85381": 395000, "85382": 405000,
    "85383": 420000,
    # Surprise / Sun City
    "85374": 360000, "85375": 380000, "85378": 340000, "85379": 355000,
    "85387": 390000,
    # Buckeye / Goodyear / Avondale / Tolleson
    "85326": 330000, "85338": 355000, "85340": 360000, "85353": 300000,
    "85392": 350000, "85395": 370000,
    # Queen Creek / San Tan Valley
    "85140": 450000, "85142": 510000, "85143": 430000,
    # Maricopa / Casa Grande
    "85138": 300000, "85139": 290000, "85122": 280000, "85194": 275000,
    # Tucson area
    "85701": 240000, "85704": 280000, "85705": 220000, "85706": 215000,
    "85710": 245000, "85711": 235000, "85712": 255000, "85713": 200000,
    "85714": 195000, "85715": 270000, "85716": 265000, "85718": 380000,
    "85719": 260000, "85730": 240000, "85741": 290000, "85742": 310000,
    "85743": 295000, "85745": 270000, "85746": 250000, "85747": 285000,
    "85748": 310000, "85749": 330000, "85750": 350000,
    # Flagstaff
    "86001": 510000, "86004": 490000, "86005": 520000,
    # Sedona / Verde Valley
    "86336": 640000, "86351": 480000,
    # Prescott
    "86301": 430000, "86303": 420000, "86305": 460000,
    # Lake Havasu / Kingman
    "86403": 340000, "86409": 250000,
    # Yuma
    "85364": 240000, "85365": 230000, "85367": 235000,
}

# AZ statewide fallback for unknown zips
AZ_MEDIAN_HOME_VALUE = 420000

# Solar premium research data
SOLAR_PREMIUM_PCT = 0.040        # 4.0% avg premium (Zillow/LBNL)
SOLAR_PREMIUM_PER_WATT = 14.77  # $14.77/W avg sold premium (LBNL Solarize study)
SOLAR_PREMIUM_LOW_PCT = 0.030   # Conservative: 3%
SOLAR_PREMIUM_HIGH_PCT = 0.057  # Aggressive: 5.7% (LBNL "new" markets)

# AZ utility bill escalation (APS/SRP historical avg)
AZ_RATE_ESCALATION = 0.035  # 3.5%/yr

def extract_zip(address: str) -> str | None:
    """Extract US zip code from an address string."""
    m = re.search(r'\b(\d{5})(?:-\d{4})?\b', address)
    return m.group(1) if m else None

def estimate_home_value(address: str = None, zip_code: str = None) -> dict:
    """
    Estimate home value for an AZ address.
    Returns dict with value, zip, source, confidence.
    """
    z = zip_code
    if not z and address:
        z = extract_zip(address)

    if z and z in AZ_ZIP_HOME_VALUES:
        return {
            "estimated_value": AZ_ZIP_HOME_VALUES[z],
            "zip": z,
            "source": "AZ zip code median (2024 Zillow Research)",
            "confidence": "medium",
        }
    elif z:
        # Unknown AZ zip — use state median
        return {
            "estimated_value": AZ_MEDIAN_HOME_VALUE,
            "zip": z,
            "source": "AZ statewide median (2024) — zip not in database",
            "confidence": "low",
        }
    else:
        return {
            "estimated_value": AZ_MEDIAN_HOME_VALUE,
            "zip": None,
            "source": "AZ statewide median (2024) — no zip found",
            "confidence": "low",
        }

def calculate_home_value_impact(
    address: str = None,
    monthly_bill: float = 175.0,
    system_kw: float = None,
    yr1_savings: float = None,
    payback_yrs: float = None,
    zip_code: str = None,
    enrichment: dict = None,
) -> dict:
    """
    Full home equity & solar value impact calculation.

    If enrichment dict is provided (from enrich_lead()), uses real solar data.
    Otherwise estimates from monthly_bill.
    """
    # ── 1. Pull enrichment data if provided ──
    score = None
    grade = None
    priority = None
    panels = None
    sun_hours = None
    system_kw_api = None

    if enrichment and not enrichment.get("error"):
        score     = enrichment.get("lead_score")
        grade     = enrichment.get("lead_grade")
        priority  = enrichment.get("priority")
        panels    = enrichment.get("panels")
        sun_hours = enrichment.get("sun_hours")
        yr1_savings  = yr1_savings or enrichment.get("yr1_savings") or enrichment.get("savings_yr1")
        payback_yrs  = payback_yrs or enrichment.get("payback_yrs")
        system_kw_api = enrichment.get("system_kw")
        # address enrichment
        if not address and enrichment.get("formatted_address"):
            address = enrichment["formatted_address"]

    # ── 2. Home value estimate ──
    home = estimate_home_value(address=address, zip_code=zip_code)
    home_value = home["estimated_value"]

    # ── 3. System size estimate (if not from enrichment) ──
    if system_kw is None:
        if system_kw_api:
            system_kw = system_kw_api
        else:
            # Estimate: avg AZ home needs ~1.1W per $1/mo bill
            # (monthly kWh ≈ bill/0.14; system kW = annual kWh/1800 sun-hrs)
            monthly_kwh = monthly_bill / 0.14
            annual_kwh = monthly_kwh * 12
            system_kw = round(annual_kwh / 1750, 1)  # 1750 sun-hrs/yr in AZ

    system_w = system_kw * 1000

    # ── 4. Year-1 savings estimate (if not from enrichment) ──
    if yr1_savings is None:
        yr1_savings = monthly_bill * 12 * 0.90  # 90% offset assumption

    # ── 5. Payback estimate (if not from enrichment) ──
    if payback_yrs is None:
        install_cost_per_w = 2.85  # avg AZ installed cost after ITC
        install_cost = system_w * install_cost_per_w
        payback_yrs = round(install_cost / yr1_savings, 1) if yr1_savings > 0 else 8.0

    # ── 6. Federal ITC (30%) ──
    gross_system_cost = system_w * 3.80  # avg AZ pre-incentive gross cost per watt
    federal_itc = gross_system_cost * 0.30
    net_system_cost = gross_system_cost - federal_itc

    # ── 7. Solar home value premium ──
    # Method A: Percentage of home value (Zillow/NREL 4%)
    value_premium_pct    = home_value * SOLAR_PREMIUM_PCT
    value_premium_pct_lo = home_value * SOLAR_PREMIUM_LOW_PCT
    value_premium_pct_hi = home_value * SOLAR_PREMIUM_HIGH_PCT

    # Method B: Per-watt premium (LBNL $14.77/W)
    value_premium_per_w  = system_w * SOLAR_PREMIUM_PER_WATT

    # Blended estimate: average of methods
    value_premium_mid = (value_premium_pct + value_premium_per_w) / 2

    # Low/High range
    value_premium_low  = value_premium_pct_lo
    value_premium_high = value_premium_pct_hi

    # ── 8. New home value post-solar ──
    new_home_value_mid = home_value + value_premium_mid
    new_home_value_low = home_value + value_premium_low
    new_home_value_high = home_value + value_premium_high

    # ── 9. 25-year cumulative savings (with AZ escalation) ──
    savings_25yr = 0.0
    s = yr1_savings
    for _ in range(25):
        savings_25yr += s
        s *= (1 + AZ_RATE_ESCALATION)
    savings_25yr = round(savings_25yr, 0)

    # 25-yr total bills WITHOUT solar (escalating)
    bill_25yr = 0.0
    b = monthly_bill * 12
    for _ in range(25):
        bill_25yr += b
        b *= (1 + AZ_RATE_ESCALATION)
    bill_25yr = round(bill_25yr, 0)

    # ── 10. Combined ROI ──
    total_roi_mid  = savings_25yr + value_premium_mid - net_system_cost
    total_roi_high = savings_25yr + value_premium_high - net_system_cost
    roi_pct_mid    = (total_roi_mid / net_system_cost * 100) if net_system_cost > 0 else 0

    # ── 11. Sell scenarios ──
    def sell_scenario(years_out: int) -> dict:
        """If they sell in N years, total realized value."""
        savings_to_sale = 0.0
        s2 = yr1_savings
        for _ in range(years_out):
            savings_to_sale += s2
            s2 *= (1 + AZ_RATE_ESCALATION)
        equity_gain = value_premium_mid
        total_gain  = savings_to_sale + equity_gain - net_system_cost
        return {
            "years": years_out,
            "energy_savings": round(savings_to_sale, 0),
            "equity_gain": round(equity_gain, 0),
            "net_cost": round(net_system_cost, 0),
            "total_gain": round(total_gain, 0),
            "profitable": total_gain > 0,
        }

    sell_1yr  = sell_scenario(1)
    sell_3yr  = sell_scenario(3)
    sell_5yr  = sell_scenario(5)
    sell_7yr  = sell_scenario(7)
    sell_10yr = sell_scenario(10)

    # ── 12. Talking points ──
    city_str = ""
    if address:
        parts = address.split(",")
        if len(parts) >= 2:
            city_str = parts[-2].strip().split()[0]

    equity_pct = (value_premium_mid / home_value * 100) if home_value else 0

    talking_points = [
        f"Solar adds an estimated ${value_premium_mid:,.0f} to your home's resale value "
        f"— that's a {equity_pct:.1f}% equity boost before you save a single dollar on energy.",

        f"You're currently spending ${monthly_bill * 12:,.0f}/year on electricity. Over 25 years, "
        f"with AZ's rate increases, that's ${bill_25yr:,.0f} going straight to the utility. "
        f"Solar locks in your rate today.",

        f"With the 30% federal tax credit, your net investment is only ${net_system_cost:,.0f}. "
        f"Your year-one energy savings alone are ${yr1_savings:,.0f} — that's a "
        f"{yr1_savings / net_system_cost * 100:.0f}% first-year cash-on-cash return.",

        f"If you sell in 5 years, you'll have pocketed ${sell_5yr['energy_savings']:,.0f} in energy "
        f"savings PLUS added ${sell_5yr['equity_gain']:,.0f} to your sale price — a combined "
        f"${sell_5yr['total_gain']:,.0f} gain on a ${net_system_cost:,.0f} investment.",

        f"Nationally, solar-equipped homes sell 4.1% faster and for more money. In AZ's hot market, "
        f"solar is one of the few upgrades that pays YOU back both monthly and at closing.",

        f"Unlike a kitchen remodel (50-75¢ on the dollar) or a pool (30-50¢ on the dollar), "
        f"solar typically returns more than $1 for every $1 invested at resale — PLUS "
        f"you collect energy savings every month until you sell.",

        f"Mortgage lenders now recognize solar in home appraisals. Adding ${value_premium_mid:,.0f} "
        f"in solar equity means your home's appraised value increases — giving you more borrowing "
        f"power if you ever refinance.",
    ]

    return {
        # identity
        "address": address,
        "zip": home["zip"],
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),

        # lead scoring (if enriched)
        "lead_score": score,
        "lead_grade": grade,
        "priority": priority,

        # system
        "system_kw": round(system_kw, 1),
        "system_w": round(system_w, 0),
        "panels": panels,
        "sun_hours": sun_hours,

        # costs
        "monthly_bill": round(monthly_bill, 2),
        "gross_system_cost": round(gross_system_cost, 0),
        "federal_itc": round(federal_itc, 0),
        "net_system_cost": round(net_system_cost, 0),

        # savings
        "yr1_savings": round(yr1_savings, 0),
        "payback_yrs": payback_yrs,
        "savings_25yr": round(savings_25yr, 0),
        "bill_25yr": round(bill_25yr, 0),

        # home value
        "home_value_estimate": round(home_value, 0),
        "home_value_source": home["source"],
        "home_value_confidence": home["confidence"],
        "value_premium_low": round(value_premium_low, 0),
        "value_premium_mid": round(value_premium_mid, 0),
        "value_premium_high": round(value_premium_high, 0),
        "new_home_value_low": round(new_home_value_low, 0),
        "new_home_value_mid": round(new_home_value_mid, 0),
        "new_home_value_high": round(new_home_value_high, 0),
        "equity_pct": round(equity_pct, 2),

        # combined ROI
        "total_roi_mid": round(total_roi_mid, 0),
        "total_roi_high": round(total_roi_high, 0),
        "roi_pct_mid": round(roi_pct_mid, 1),

        # sell scenarios
        "sell_scenarios": {
            "1yr": sell_1yr, "3yr": sell_3yr, "5yr": sell_5yr,
            "7yr": sell_7yr, "10yr": sell_10yr,
        },

        # talking points
        "talking_points": talking_points,

        # data source
        "data_sources": [
            "Zillow Research: Solar Premium Study (2021) — 4.1% avg value increase",
            "LBNL Electricity Markets and Policy: Sold Premium $14.77/W (Solarize study)",
            "NREL: PVWatts solar generation model for AZ",
            "APS/SRP: 3.5% avg annual rate escalation (2019–2024 historical)",
            "IRS: 30% Residential Clean Energy Credit (§25D)",
        ],
    }


# ─────────────────────────────────────────────
# TERMINAL REPORT RENDERER
# ─────────────────────────────────────────────

def _c(text, code, use_color=True):
    if not use_color:
        return str(text)
    return f"\033[{code}m{text}\033[0m"

def _bar(value, max_val=100, width=30, use_color=True) -> str:
    filled = int(min(value, max_val) / max_val * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = value / max_val * 100
    if pct >= 70:
        color = "92"  # bright green
    elif pct >= 40:
        color = "93"  # yellow
    else:
        color = "91"  # red
    return _c(bar, color, use_color)

def render_report(data: dict, use_color: bool = True) -> str:
    lines = []
    C = lambda t, code: _c(t, code, use_color)

    def hr(char="─", width=70):
        lines.append(C(char * width, "90"))

    def section(title):
        lines.append("")
        lines.append(C(f"  {'▌ ' + title}", "1;36"))
        hr("─", 68)

    # ── Header ──
    hr("═")
    lines.append(C("  🏡  SOLAR HOME VALUE IMPACT REPORT", "1;33"))
    if data.get("address"):
        lines.append(C(f"  {data['address']}", "37"))
    lines.append(C(f"  Generated: {data['generated_at']}", "90"))
    hr("═")

    # ── Lead Score (if enriched) ──
    if data.get("lead_score") is not None:
        score = data["lead_score"]
        grade = data.get("lead_grade", "?")
        pri   = data.get("priority", "")
        pri_color = {"HOT": "91", "WARM": "93", "COOL": "94", "LOW": "90"}.get(pri, "37")
        lines.append("")
        lines.append(f"  Solar Score:  {_bar(score, use_color=use_color)} {C(f'{score}/100', '1;97')}  "
                     f"[{C(grade, '1;97')}] {C(pri, pri_color)}")

    # ── Current Home Value ──
    section("CURRENT HOME VALUE ESTIMATE")
    hv = data["home_value_estimate"]
    lines.append(f"  Estimated Value  : {C(f'${hv:,.0f}', '1;97')}")
    lines.append(f"  Source           : {C(data['home_value_source'], '90')}")
    lines.append(f"  Confidence       : {C(data['home_value_confidence'].upper(), '93')}")

    # ── System & Savings ──
    section("SOLAR SYSTEM OVERVIEW")
    sys_kw_str  = "{:.1f} kW".format(data['system_kw'])
    bill_str    = "${:,.0f}/mo".format(data['monthly_bill'])
    yr1_str     = "${:,.0f}".format(data['yr1_savings'])
    pay_str     = "{:.1f} years".format(data['payback_yrs'])
    s25_str     = "${:,.0f}".format(data['savings_25yr'])
    bill25_str  = "${:,.0f}  \u2190 going to APS".format(data['bill_25yr'])
    lines.append(f"  System Size      : {C(sys_kw_str, '1;97')}")
    if data.get("panels"):
        lines.append(f"  Panel Count      : {C(str(data['panels']), '1;97')}")
    lines.append(f"  Monthly Bill     : {C(bill_str, '1;97')}")
    lines.append(f"  Year-1 Savings   : {C(yr1_str, '92')}")
    lines.append(f"  Payback Period   : {C(pay_str, '1;97')}")
    lines.append(f"  25-yr Savings    : {C(s25_str, '92')}")
    lines.append(f"  25-yr Bills W/O  : {C(bill25_str, '91')}")

    # ── Home Value Premium ──
    section("SOLAR HOME VALUE PREMIUM (Research-Backed)")
    lo  = data["value_premium_low"]
    mid = data["value_premium_mid"]
    hi  = data["value_premium_high"]
    pct = data["equity_pct"]

    lines.append(f"  Percentage (3%)    : {C('+${:,.0f}'.format(lo), '93')}  (Zillow conservative)")
    lines.append(f"  Percentage (4%)    : {C('+${:,.0f}'.format(round(data['home_value_estimate'] * SOLAR_PREMIUM_PCT, 0)), '93')}  (Zillow/NREL avg)")
    system_w_r = data["system_w"]
    per_w_str = "${:,.0f}".format(system_w_r * SOLAR_PREMIUM_PER_WATT)
    lines.append(f"  Per-Watt ($14.77/W): {C('+' + per_w_str, '93')}  (LBNL study)")
    lines.append(f"  Optimistic (+5.7%) : {C('+${:,.0f}'.format(hi), '92')}")
    lines.append("")
    nhmv_str = "${:,.0f}".format(data["new_home_value_mid"])
    pct_str  = "+{:.1f}%".format(pct)
    lines.append(f"  New Home Value   : {C(nhmv_str, '1;97')}  "
                 f"({C(pct_str, '92')} equity boost)")

    # ── If They Sell ──
    section("RESALE VALUE IMPACT — IF YOU SELL IN...")
    scenarios = data["sell_scenarios"]
    headers = ["Years", "Energy $", "Equity +$", "Net Cost", "TOTAL GAIN", "Profitable?"]
    lines.append(f"  {C('Years', '1;37'):>6}  {C('Energy Saved', '1;37'):>14}  "
                 f"{C('Home Value +', '1;37'):>13}  {C('Net Cost', '1;37'):>12}  "
                 f"{C('TOTAL GAIN', '1;37'):>12}  {C('Status', '1;37'):<10}")
    hr("─", 80)
    for key, sc in scenarios.items():
        gain_color = "92" if sc["profitable"] else "91"
        status     = "✅ Profit" if sc["profitable"] else "❌ Loss"
        yr_lbl     = str(sc["years"]) + " yr"
        e_str      = "${:>10,.0f}".format(sc["energy_savings"])
        eq_str     = "+${:>8,.0f}".format(sc["equity_gain"])
        nc_str     = "-${:>8,.0f}".format(sc["net_cost"])
        tg_str     = "${:>8,.0f}".format(sc["total_gain"])
        lines.append(
            "  {:>6}  {:>14}    {:>13}    {:>12}    {:>12}  {}".format(
                C(yr_lbl, "37"),
                C(e_str, "37"),
                C(eq_str, "92"),
                C(nc_str, "91"),
                C(tg_str, gain_color),
                C(status, gain_color),
            )
        )

    # ── Total 25-yr ROI ──
    section("25-YEAR COMBINED ROI SUMMARY")
    roi   = data["total_roi_mid"]
    roi_p = data["roi_pct_mid"]
    nc    = data["net_system_cost"]
    nc_str2  = "-${:,.0f}".format(nc)
    e25_str  = "+${:,.0f}".format(data["savings_25yr"])
    hv_str2  = "+${:,.0f}".format(data["value_premium_mid"])
    roi_str  = "${:,.0f}".format(roi)
    roip_str = "{:.0f}%".format(roi_p)
    lines.append(f"  Net Investment   : {C(nc_str2, '91')}  (after 30% ITC)")
    lines.append(f"  25-yr Energy $   : {C(e25_str, '92')}")
    lines.append(f"  Home Value +     : {C(hv_str2, '92')}")
    lines.append("  " + "\u2500" * 41)
    lines.append(f"  TOTAL 25-yr ROI  : {C(roi_str, '1;92')}  ({C(roip_str, '1;92')} return on investment)")

    # ── Talking Points ──
    section("🎯 REP TALKING POINTS")
    for i, tp in enumerate(data["talking_points"][:5], 1):
        # Word-wrap at ~65 chars
        words = tp.split()
        curr_line = f"  {i}. "
        for w in words:
            if len(curr_line) + len(w) + 1 > 72:
                lines.append(C(curr_line, "37"))
                curr_line = "     " + w + " "
            else:
                curr_line += w + " "
        lines.append(C(curr_line.rstrip(), "37"))
        lines.append("")

    # ── Data Sources ──
    lines.append(C("  📚 Research Sources:", "90"))
    for src in data["data_sources"]:
        lines.append(C(f"     • {src}", "90"))

    hr("═")
    lines.append(C(f"  Solar Intelligence Suite — {data['generated_at']}", "90"))
    hr("═")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# MAIN CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Solar Home Value & Equity Impact Report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/home_value_impact.py "1905 E Marquette Dr, Gilbert, AZ" --bill 175
  python scripts/home_value_impact.py --zip 85234 --bill 175
  python scripts/home_value_impact.py --zip 85254 --bill 200 --no-enrich
  python scripts/home_value_impact.py --zip 85001 --json
  python scripts/home_value_impact.py "4521 N 44th St, Phoenix, AZ" --bill 220 --no-color
        """
    )
    parser.add_argument("address", nargs="?", help="Full street address")
    parser.add_argument("--bill",      type=float, default=175.0, help="Monthly utility bill ($)")
    parser.add_argument("--zip",       type=str,   default=None,  help="AZ zip code (alternative to address)")
    parser.add_argument("--no-enrich", action="store_true",       help="Skip Google Solar API enrichment")
    parser.add_argument("--json",      action="store_true",       help="Output raw JSON")
    parser.add_argument("--no-color",  action="store_true",       help="Plain text, no ANSI colors")
    args = parser.parse_args()

    if not args.address and not args.zip:
        parser.error("Provide an address or --zip code")

    enrichment = None
    if args.address and not args.no_enrich:
        try:
            from core.solar import enrich_lead
            print(_c("  🔍 Enriching with Google Solar API...", "90", not args.no_color), file=sys.stderr)
            enrichment = enrich_lead(args.address, monthly_bill=args.bill)
        except Exception as e:
            print(_c(f"  ⚠ Enrichment failed: {e} — using estimate mode", "93", not args.no_color), file=sys.stderr)

    data = calculate_home_value_impact(
        address=args.address,
        monthly_bill=args.bill,
        zip_code=args.zip,
        enrichment=enrichment,
    )

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(render_report(data, use_color=not args.no_color))


if __name__ == "__main__":
    main()
