#!/usr/bin/env python3
"""
Cost of Waiting Calculator
===========================
Shows homeowners the real dollar cost of delaying solar adoption.
Factors in: utility rate escalation, continued electricity spend,
ITC percentage cliff, and lost savings accumulation.

CLI:
    python scripts/cost_of_waiting.py "1905 E Marquette Dr, Gilbert AZ" --bill 175
    python scripts/cost_of_waiting.py "address" --bill 195 --months 18 --json
    python scripts/cost_of_waiting.py --bill 175 --no-enrich   # bill-only mode

Importable:
    from scripts.cost_of_waiting import calculate_waiting_cost
"""

import sys, os, json, argparse, math
from datetime import datetime, date

sys.path.insert(0, "/root/solar-tools")

# ── Constants ────────────────────────────────────────────────────────────────
DEFAULT_RATE_ESCALATION = 0.035   # 3.5% average annual utility rate increase (EIA avg)
DEFAULT_ITC_PCT         = 0.30    # Current federal ITC (30% through 2032)
INSTALL_DELAY_MONTHS    = 2       # Avg months from quote to install
MONTHS_OPTIONS          = [3, 6, 12, 18, 24]


def calculate_waiting_cost(
    monthly_bill: float,
    annual_savings_yr1: float = None,
    net_system_cost: float = None,
    payback_years: float = None,
    months_to_evaluate: int = 12,
    utility_rate_escalation: float = DEFAULT_RATE_ESCALATION,
    itc_pct: float = DEFAULT_ITC_PCT,
    system_size_kw: float = None,
    panels: int = None,
) -> dict:
    """
    Calculate the financial cost of waiting N months before going solar.

    Returns a dict with per-month and summary waiting cost data.
    """
    # ── If no solar data provided, estimate from bill ─────────────────────────
    if annual_savings_yr1 is None:
        # Rough estimate: ~75% of bill goes to charges solar can offset
        annual_savings_yr1 = monthly_bill * 12 * 0.72

    if net_system_cost is None:
        # Industry avg: ~$3/W, 10-12 panels per $175/mo bill
        kw_estimate = max(4.0, (monthly_bill / 175) * 7.5)
        gross = kw_estimate * 3000
        net_system_cost = gross * (1 - itc_pct)

    if payback_years is None:
        payback_years = net_system_cost / max(annual_savings_yr1, 1)

    monthly_savings = annual_savings_yr1 / 12

    # ── Cost accumulation per month waiting ──────────────────────────────────
    cumulative_electricity_paid = 0
    cumulative_lost_savings      = 0
    monthly_bill_current         = monthly_bill
    months_detail                = []

    for m in range(1, months_to_evaluate + 1):
        # Utility rate escalation (applied monthly, proportionally)
        monthly_rate_increase = (1 + utility_rate_escalation) ** (m / 12)
        bill_this_month       = monthly_bill * monthly_rate_increase

        # Cumulative electricity paid while waiting
        cumulative_electricity_paid += bill_this_month

        # Lost savings: the solar system would have generated savings starting month 1
        # But we also account for install delay: system live after INSTALL_DELAY_MONTHS
        if m > INSTALL_DELAY_MONTHS:
            savings_month_idx      = m - INSTALL_DELAY_MONTHS
            savings_rate_increase  = (1 + utility_rate_escalation) ** (savings_month_idx / 12)
            lost_this_month        = monthly_savings * savings_rate_increase
            cumulative_lost_savings += lost_this_month

        if m in MONTHS_OPTIONS or m == months_to_evaluate:
            months_detail.append({
                "months":                     m,
                "electricity_paid_usd":       round(cumulative_electricity_paid, 2),
                "lost_solar_savings_usd":     round(cumulative_lost_savings, 2),
                "total_cost_of_waiting_usd":  round(cumulative_electricity_paid + cumulative_lost_savings, 2),
                "monthly_bill_at_delay_end":  round(bill_this_month, 2),
                "equivalent_panels":          round((cumulative_electricity_paid + cumulative_lost_savings) / 280, 1) if system_size_kw else None,
            })

    # ── 12-month summary (main figure) ───────────────────────────────────────
    twelve_mo = next((d for d in months_detail if d["months"] == 12), months_detail[-1])

    # ── ITC note ──────────────────────────────────────────────────────────────
    itc_amount     = net_system_cost / (1 - itc_pct) * itc_pct  # gross cost * ITC
    itc_note       = f"Federal 30% ITC ({itc_pct:.0%}) is currently stable through 2032."
    itc_risk_note  = ""
    current_year   = date.today().year
    if current_year >= 2032:
        itc_risk_note = "⚠️  ITC step-down risk: consult current policy."

    # ── Monthly bill at start of year 2 ──────────────────────────────────────
    yr2_monthly = monthly_bill * (1 + utility_rate_escalation)
    yr5_monthly = monthly_bill * (1 + utility_rate_escalation) ** 5

    # ── Talking points (closing arguments) ───────────────────────────────────
    cost_12mo = twelve_mo["total_cost_of_waiting_usd"]
    lost_12mo = twelve_mo["lost_solar_savings_usd"]
    elec_12mo = twelve_mo["electricity_paid_usd"]

    talking_points = [
        f"Every month you wait costs ${monthly_savings:,.0f} in electricity savings you never get back.",
        f"Over the next 12 months, you'll pay ${elec_12mo:,.0f} to the utility — money solar would eliminate.",
        f"Waiting 12 months costs ${cost_12mo:,.0f} total: ${elec_12mo:,.0f} in bills + ${lost_12mo:,.0f} in lost savings.",
        f"At {utility_rate_escalation:.1%}/year rate escalation, your bill grows to ${yr2_monthly:,.0f}/mo next year and ${yr5_monthly:,.0f}/mo in 5 years.",
        f"The federal ITC saves you ${itc_amount:,.0f} off your system — that incentive exists now.",
        f"Your system pays itself back in {payback_years:.1f} years — then 15+ years of free electricity.",
        f"Every day you run the utility's meter is money that could be growing your equity instead.",
    ]

    return {
        "monthly_bill":             round(monthly_bill, 2),
        "annual_savings_yr1_usd":   round(annual_savings_yr1, 2),
        "net_system_cost_usd":      round(net_system_cost, 2),
        "payback_years":            round(payback_years, 1),
        "monthly_savings_usd":      round(monthly_savings, 2),
        "itc_amount_usd":           round(itc_amount, 2),
        "itc_pct":                  itc_pct,
        "itc_note":                 itc_note,
        "itc_risk_note":            itc_risk_note,
        "utility_rate_escalation":  utility_rate_escalation,
        "yr1_monthly_bill":         round(monthly_bill, 2),
        "yr2_monthly_bill":         round(yr2_monthly, 2),
        "yr5_monthly_bill":         round(yr5_monthly, 2),
        "months_evaluated":         months_to_evaluate,
        "twelve_month_summary":     twelve_mo,
        "monthly_breakdown":        months_detail,
        "talking_points":           talking_points,
        "system_size_kw":           system_size_kw,
        "panels":                   panels,
    }


# ── ANSI terminal report ─────────────────────────────────────────────────────
def _c(code, text, use_color=True):
    return f"\033[{code}m{text}\033[0m" if use_color else text

def print_waiting_report(lead: dict, waiting: dict, address: str, use_color: bool = True):
    C = lambda code, t: _c(code, t, use_color)
    W  = 64

    def hdr(title):
        pad = (W - len(title) - 2) // 2
        line = "─" * pad + f" {title} " + "─" * (W - pad - len(title) - 2)
        print(C("33;1", line))

    def bar(val, max_val=24, width=30, label=""):
        filled = min(int((val / max(max_val, 1)) * width), width)
        color = "31;1" if val >= 18 else ("33;1" if val >= 9 else "32;1")
        b = "█" * filled + "░" * (width - filled)
        return C(color, f"[{b}]") + (f" {label}" if label else "")

    # ── Header ────────────────────────────────────────────────────────────────
    print()
    print(C("36;1", "═" * W))
    print(C("36;1", "  ☀  COST OF WAITING ANALYSIS  ☀".center(W)))
    print(C("36;1", "═" * W))
    print(C("37", f"  {address}"))
    bill_str = f"${waiting['monthly_bill']:,.0f}"
    print(C("37", f"  Current monthly bill: {C('33;1', bill_str)}/mo  |  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
    print(C("36;1", "═" * W))

    # ── Cost of Waiting Summary ───────────────────────────────────────────────
    hdr("COST OF WAITING — SUMMARY")
    twelve = waiting["twelve_month_summary"]
    print(f"  {'Months Waiting':<28} {'Electricity Paid':>16}  {'Lost Savings':>12}  {'TOTAL COST':>10}")
    print(C("90", "  " + "─" * (W - 2)))

    for item in waiting["monthly_breakdown"]:
        m        = item["months"]
        elec     = item["electricity_paid_usd"]
        lost     = item["lost_solar_savings_usd"]
        total    = item["total_cost_of_waiting_usd"]
        if m == 12:
            color = "31;1"
        elif m <= 6:
            color = "32"
        else:
            color = "33"
        print(C(color, f"  {m:>2} months{'':<21} ${elec:>13,.0f}  ${lost:>11,.0f}  ${total:>9,.0f}"))

    # ── 12-Month highlight ────────────────────────────────────────────────────
    print()
    print(C("31;1", f"  ⚠  WAITING 12 MONTHS COSTS YOU ${twelve['total_cost_of_waiting_usd']:,.0f}  ⚠"))
    print(C("31",   f"     (${twelve['electricity_paid_usd']:,.0f} in electric bills + ${twelve['lost_solar_savings_usd']:,.0f} in lost solar savings)"))

    # ── Bill Escalation ───────────────────────────────────────────────────────
    hdr("YOUR BILL OVER TIME (Without Solar)")
    esc = waiting["utility_rate_escalation"]
    bill = waiting["monthly_bill"]
    print(f"  {'Year':<10} {'Monthly Bill':>14}  {'Annual Bill':>12}  {'Increase':>10}")
    print(C("90", "  " + "─" * (W - 2)))
    for yr, mo_bill in [
        ("Now",    bill),
        ("Year 1", bill * (1 + esc)),
        ("Year 2", bill * (1 + esc)**2),
        ("Year 5", bill * (1 + esc)**5),
        ("Year 10", bill * (1 + esc)**10),
        ("Year 20", bill * (1 + esc)**20),
    ]:
        increase = mo_bill - bill
        color = "31;1" if yr in ("Year 10","Year 20") else ("33" if yr in ("Year 5",) else "37")
        increase_str = "+$" + f"{increase:,.0f}"
        print(C(color, f"  {yr:<10} ${mo_bill:>12,.0f}  ${mo_bill*12:>11,.0f}  {increase_str:>10}"))
    print()
    print(C("33", f"  Avg utility rate escalation: {esc:.1%}/year (EIA national average)"))

    # ── Solar System Value ────────────────────────────────────────────────────
    if lead:
        hdr("YOUR SOLAR SYSTEM (Lock In Today)")
        score    = lead.get("lead_score", 0)
        grade    = lead.get("lead_grade", "?")
        priority = lead.get("priority", "")
        savings  = lead.get("annual_savings_yr1_usd", waiting["annual_savings_yr1_usd"])
        net_cost = lead.get("net_cost_usd", waiting["net_system_cost_usd"])
        payback  = lead.get("payback_years", waiting["payback_years"])
        kw       = lead.get("system_size_kw", waiting.get("system_size_kw", "?"))
        panels   = lead.get("panels_recommended", waiting.get("panels", "?"))
        itc      = waiting["itc_amount_usd"]
        roi25    = lead.get("roi_25yr_pct", 0)

        grade_color = "32;1" if priority == "HOT" else ("33;1" if priority == "WARM" else "37")
        print(f"  Lead Score:  {bar(score, 100, 20)}  {C(grade_color, f'{grade} {priority}')} ({score}/100)")
        print()
        print(f"  {'Year 1 Savings:':<28} {C('32;1', f'${savings:,.0f}/yr')}")
        print(f"  {'Monthly Savings:':<28} {C('32;1', f'${savings/12:,.2f}/mo')}")
        print(f"  {'System Size:':<28} {kw} kW  ({panels} panels)")
        print(f"  {'Net Cost After ITC:':<28} ${net_cost:,.0f}")
        print(f"  {'ITC Credit (30%):':<28} {C('33;1', f'${itc:,.0f} back')}")
        print(f"  {'Simple Payback:':<28} {payback:.1f} years")
        if roi25:
            print(f"  {'25-Year ROI:':<28} {C('32;1', f'{roi25:,.0f}%')}")

    # ── Talking Points ────────────────────────────────────────────────────────
    hdr("CLOSING TALKING POINTS")
    for i, pt in enumerate(waiting["talking_points"], 1):
        # word wrap at 58 chars
        words  = pt.split()
        lines  = []
        cur    = ""
        for w in words:
            if len(cur) + len(w) + 1 > 58:
                lines.append(cur)
                cur = w
            else:
                cur = cur + " " + w if cur else w
        if cur:
            lines.append(cur)
        print(C("37;1", f"  {i}. {lines[0]}"))
        for l in lines[1:]:
            print(C("37",   f"     {l}"))
        print()

    print(C("36;1", "═" * W))
    print(C("36;1", "  Every day is a decision. Make the right one today."))
    print(C("36;1", "═" * W))
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Solar Cost of Waiting Calculator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python scripts/cost_of_waiting.py "1905 E Marquette Dr, Gilbert AZ" --bill 175
  python scripts/cost_of_waiting.py "address" --bill 225 --months 18
  python scripts/cost_of_waiting.py --bill 195 --no-enrich
  python scripts/cost_of_waiting.py "address" --bill 175 --json
"""
    )
    parser.add_argument("address", nargs="?", help="Property address to analyze")
    parser.add_argument("--bill",      type=float, default=175, help="Monthly electric bill (default: 175)")
    parser.add_argument("--rate",      type=float, default=0.14, help="Utility rate $/kWh (default: 0.14)")
    parser.add_argument("--months",    type=int,   default=24, help="Months to evaluate (default: 24)")
    parser.add_argument("--escalation",type=float, default=DEFAULT_RATE_ESCALATION,
                        help=f"Annual utility rate increase (default: {DEFAULT_RATE_ESCALATION})")
    parser.add_argument("--no-enrich", action="store_true", help="Skip Solar API — bill-only mode")
    parser.add_argument("--json",      action="store_true", help="Output raw JSON")
    parser.add_argument("--no-color",  action="store_true", help="Disable ANSI color output")
    args = parser.parse_args()

    lead = {}
    if args.address and not args.no_enrich:
        try:
            from core.solar import enrich_lead
            print(f"Enriching {args.address}..." if not args.json else "", end="", flush=True)
            lead = enrich_lead(args.address, args.bill, args.rate)
            if not args.json:
                print(" Done.")
        except Exception as e:
            print(f"Warning: Could not enrich ({e}) — using bill-only mode", file=sys.stderr)
            lead = {}

    waiting = calculate_waiting_cost(
        monthly_bill        = args.bill,
        annual_savings_yr1  = lead.get("annual_savings_yr1_usd"),
        net_system_cost     = lead.get("net_cost_usd"),
        payback_years       = lead.get("payback_years"),
        months_to_evaluate  = args.months,
        utility_rate_escalation = args.escalation,
        system_size_kw      = lead.get("system_size_kw"),
        panels              = lead.get("panels_recommended"),
    )

    if args.json:
        out = {"address": args.address, "lead": lead, "waiting_cost": waiting}
        print(json.dumps(out, indent=2))
        return

    address_label = args.address or f"${args.bill}/mo bill"
    print_waiting_report(lead, waiting, address_label, use_color=not args.no_color)


if __name__ == "__main__":
    main()
