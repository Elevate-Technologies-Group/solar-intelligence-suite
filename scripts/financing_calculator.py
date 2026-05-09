#!/usr/bin/env python3
"""
Solar Financing Calculator
Shows homeowners their $0-down monthly payment vs current bill — day-1 cash flow.
Handles the #1 door objection: "I can't afford it."

CLI:
    python scripts/financing_calculator.py "1905 E Marquette Dr, Gilbert AZ" --bill 175
    python scripts/financing_calculator.py --bill 195 --no-enrich
    python scripts/financing_calculator.py "address" --bill 175 --json

Importable:
    from scripts.financing_calculator import calculate_financing
    result = calculate_financing(lead, monthly_bill=175)
"""

import sys, os, json, math, argparse
sys.path.insert(0, "/root/solar-tools")

# ── ANSI colors ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"; YELLOW = "\033[93m"; RED    = "\033[91m"
CYAN   = "\033[96m"; WHITE  = "\033[97m"; GRAY   = "\033[90m"
BOLD   = "\033[1m";  RESET  = "\033[0m";  BLUE   = "\033[94m"
MAGENTA= "\033[95m"

# ── Financing constants ───────────────────────────────────────────────────────
LOAN_TERMS = [
    {"years": 10, "apr": 5.99, "label": "10-Year Loan"},
    {"years": 15, "apr": 6.49, "label": "15-Year Loan"},
    {"years": 20, "apr": 6.99, "label": "20-Year Loan"},
    {"years": 25, "apr": 7.49, "label": "25-Year Loan"},
]
DEFAULT_ITC_RATE       = 0.30   # 30% federal tax credit
DEFAULT_ESCALATION     = 0.035  # 3.5% annual utility rate increase
DEFAULT_SYSTEM_COST    = 3.20   # $/watt installed average
DEFAULT_UTILITY_RATE   = 0.145  # $/kWh


def monthly_payment(principal: float, annual_apr: float, years: int) -> float:
    """Standard amortizing loan monthly payment."""
    if annual_apr == 0:
        return principal / (years * 12)
    r = annual_apr / 100 / 12
    n = years * 12
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


def calculate_financing(
    lead: dict | None,
    monthly_bill: float = 175.0,
    utility_rate: float = DEFAULT_UTILITY_RATE,
    escalation_rate: float = DEFAULT_ESCALATION,
    include_state_incentive: float = 0.0,
) -> dict:
    """
    Core financing calculation. Returns full breakdown for all loan terms.

    Parameters
    ----------
    lead                 : enriched lead dict from enrich_lead() — or None
    monthly_bill         : homeowner monthly electric bill ($)
    utility_rate         : $/kWh
    escalation_rate      : annual utility rate increase (default 3.5%)
    include_state_incentive : additional % state tax credit (0.0 = none)
    """
    has_lead = lead and not lead.get("error")

    # ── Pull real solar data if available ────────────────────────────────────
    if has_lead:
        gross_cost     = lead.get("gross_cost_usd") or lead.get("gross_system_cost_usd") or (
            (lead.get("system_size_kw") or 6.5) * 1000 * DEFAULT_SYSTEM_COST
        )
        itc_credit     = lead.get("federal_itc_usd") or lead.get("federal_itc_credit_usd") or (gross_cost * DEFAULT_ITC_RATE)
        state_credit   = gross_cost * include_state_incentive
        net_cost       = gross_cost - itc_credit - state_credit
        panels         = lead.get("panels_recommended") or 20
        system_kw      = lead.get("system_size_kw") or 6.5
        annual_kwh     = lead.get("annual_kwh_produced") or lead.get("annual_kwh_production") or (system_kw * 1450)
        annual_savings = lead.get("annual_savings_yr1_usd") or (monthly_bill * 12 * 0.90)
        monthly_savings= annual_savings / 12
        address        = lead.get("formatted_address") or lead.get("address") or "Your Home"
        # imagery_date may be a dict {year, month, day} or a string
        img_date       = lead.get("imagery_date", "")
        if isinstance(img_date, dict):
            imagery_year = str(img_date.get("year", ""))
        elif isinstance(img_date, str):
            imagery_year = img_date[:4]
        else:
            imagery_year = ""
        sunshine_hrs   = lead.get("sunshine_hours_per_year") or 1800
        roof_segments  = lead.get("roof_segments") or lead.get("roof_segment_count") or 1
        score          = lead.get("lead_score") or 75
        grade          = lead.get("lead_grade") or "B"
        priority       = lead.get("priority") or "WARM"
    else:
        # Bill-only estimate mode
        annual_kwh     = (monthly_bill / utility_rate) * 12 * 0.92  # 92% offset
        system_kw      = round(annual_kwh / 1450, 1)
        panels         = max(10, round(system_kw * 3.2))
        gross_cost     = system_kw * 1000 * DEFAULT_SYSTEM_COST
        itc_credit     = gross_cost * DEFAULT_ITC_RATE
        state_credit   = gross_cost * include_state_incentive
        net_cost       = gross_cost - itc_credit - state_credit
        annual_savings = monthly_bill * 12 * 0.90
        monthly_savings= annual_savings / 12
        address        = "Your Home (estimate)"
        imagery_year   = ""
        sunshine_hrs   = 1820
        roof_segments  = 2
        score          = 0
        grade          = ""
        priority       = ""

    # ── Loan options ──────────────────────────────────────────────────────────
    options = []
    for term in LOAN_TERMS:
        pmt     = monthly_payment(net_cost, term["apr"], term["years"])
        day1    = monthly_savings - pmt         # positive = cash-flow positive day 1
        yr1_net = (monthly_savings * 12) - (pmt * 12)
        options.append({
            "label"               : term["label"],
            "years"               : term["years"],
            "apr_pct"             : term["apr"],
            "monthly_payment_usd" : round(pmt, 2),
            "monthly_savings_usd" : round(monthly_savings, 2),
            "day1_cashflow_usd"   : round(day1, 2),
            "day1_positive"       : day1 > 0,
            "yr1_net_usd"         : round(yr1_net, 2),
            "total_paid_usd"      : round(pmt * term["years"] * 12, 2),
            "total_interest_usd"  : round(pmt * term["years"] * 12 - net_cost, 2),
            "total_saved_25yr_usd": round(
                sum(
                    monthly_bill * ((1 + escalation_rate) ** y) * 12
                    for y in range(25)
                ) - pmt * term["years"] * 12,
                0
            ),
        })

    # ── Best option (most positive day-1 or least negative) ──────────────────
    best = max(options, key=lambda o: o["day1_cashflow_usd"])

    # ── Bill escalation projections ───────────────────────────────────────────
    escalation_table = []
    for yr in [1, 5, 10, 15, 20, 25]:
        future_bill = monthly_bill * ((1 + escalation_rate) ** yr)
        escalation_table.append({
            "year"       : yr,
            "bill_usd"   : round(future_bill, 2),
            "cumulative_usd": round(
                sum(monthly_bill * ((1 + escalation_rate) ** y) * 12
                    for y in range(yr)),
                0
            ),
        })

    # ── Talking points ────────────────────────────────────────────────────────
    best_pmt = best["monthly_payment_usd"]
    day1     = best["day1_cashflow_usd"]
    yr25_roi = best["total_saved_25yr_usd"]

    talking_points = [
        f"Your current bill is ${monthly_bill:.0f}/mo. With a "
        f"{best['years']}-year $0-down loan, your payment is only "
        f"${best_pmt:.0f}/mo — that's ${monthly_bill - best_pmt:.0f}/mo less than you pay today.",

        f"Day 1 you {'SAVE' if day1 >= 0 else 'pay'} ${abs(day1):.0f}/mo compared to your "
        f"current bill. You are {'cash-flow positive from day one' if day1 >= 0 else 'nearly break-even immediately'}.",

        f"Over 25 years at today's rates your utility bills would total "
        f"${sum(monthly_bill * ((1+escalation_rate)**y)*12 for y in range(25)):,.0f}. "
        f"Solar lets you own your power for ${net_cost:,.0f} total.",

        f"The 30% Federal Tax Credit reduces your system cost by ${itc_credit:,.0f} — "
        f"bringing your net investment from ${gross_cost:,.0f} down to ${net_cost:,.0f}.",

        f"Electricity rates rise ~3.5%/year. Your current ${monthly_bill:.0f} bill becomes "
        f"${monthly_bill * ((1+escalation_rate)**10):.0f}/mo in 10 years. "
        f"Your solar loan payment never changes.",

        f"With a {best['years']}-year loan at {best['apr_pct']}% APR you pay a total of "
        f"${best['total_paid_usd']:,.0f} — but save ${yr25_roi:,.0f} over 25 years.",

        f"No money down. No hidden fees. Just ${best_pmt:.0f}/mo instead of "
        f"${monthly_bill:.0f}/mo sent to the utility — money you never get back.",
    ]

    return {
        "address"               : address,
        "monthly_bill_usd"      : round(monthly_bill, 2),
        "system_size_kw"        : round(system_kw, 2),
        "panels_recommended"    : panels,
        "gross_system_cost_usd" : round(gross_cost, 2),
        "federal_itc_usd"       : round(itc_credit, 2),
        "state_incentive_usd"   : round(state_credit, 2),
        "net_cost_usd"          : round(net_cost, 2),
        "annual_savings_usd"    : round(annual_savings, 2),
        "monthly_savings_usd"   : round(monthly_savings, 2),
        "annual_kwh_production" : round(annual_kwh, 0),
        "sunshine_hours_per_year": sunshine_hrs,
        "imagery_year"          : imagery_year,
        "lead_score"            : score,
        "lead_grade"            : grade,
        "priority"              : priority,
        "loan_options"          : options,
        "recommended_option"    : best,
        "escalation_table"      : escalation_table,
        "talking_points"        : talking_points,
        "mode"                  : "enriched" if has_lead else "estimate",
    }


# ── CLI rendering ─────────────────────────────────────────────────────────────
def score_bar(score, width=30, color=True):
    filled = round(score / 100 * width)
    bar    = "█" * filled + "░" * (width - filled)
    if not color:
        return f"[{bar}] {score}/100"
    c = GREEN if score >= 70 else YELLOW if score >= 45 else RED
    return f"{c}[{bar}]{RESET} {BOLD}{score}/100{RESET}"


def cf_color(val, color):
    if not color:
        return f"{'+'if val>=0 else ''}{val:.2f}"
    c = GREEN if val >= 0 else RED
    return f"{c}{BOLD}{'+'if val>=0 else ''}{val:.2f}{RESET}"


def render_report(result: dict, color: bool = True) -> str:
    lines = []
    W = 66

    def hr(c="═"): lines.append(CYAN + c * W + RESET if color else c * W)
    def hdr(t):
        lines.append((CYAN + BOLD if color else "") + f"  {t}" + (RESET if color else ""))

    def row(label, val, vc=WHITE):
        lbl = (GRAY if color else "") + f"  {label:<36}" + (RESET if color else "")
        v   = (vc if color else "") + str(val) + (RESET if color else "")
        lines.append(f"{lbl}{v}")

    hr()
    title = "⚡  SOLAR FINANCING CALCULATOR"
    lines.append((CYAN + BOLD if color else "") + f"  {title:^{W-4}}" + (RESET if color else ""))
    hr()

    addr = result["address"]
    lines.append(f"  {(BOLD if color else '')}{addr}{(RESET if color else '')}")
    lines.append("")

    # ── System snapshot ───────────────────────────────────────────────────────
    hdr("📋  SYSTEM OVERVIEW")
    hr("─")
    row("Monthly Bill (current)", f"${result['monthly_bill_usd']:.0f}/mo",
        RED if color else "")
    row("System Size",
        f"{result['system_size_kw']:.1f} kW  |  {result['panels_recommended']} panels")
    row("Annual Production",
        f"{result['annual_kwh_production']:,.0f} kWh/yr")
    row("Monthly Savings",
        f"${result['monthly_savings_usd']:.0f}/mo  (${result['annual_savings_usd']:,.0f}/yr)",
        GREEN if color else "")
    row("Gross System Cost",     f"${result['gross_system_cost_usd']:,.0f}")
    row("Federal Tax Credit (30%)", f"-${result['federal_itc_usd']:,.0f}",
        GREEN if color else "")
    if result["state_incentive_usd"] > 0:
        row("State Incentive",   f"-${result['state_incentive_usd']:,.0f}",
            GREEN if color else "")
    row("Net Cost After Credits", f"${result['net_cost_usd']:,.0f}",
        YELLOW if color else "")
    if result["lead_score"]:
        lines.append("")
        row("Lead Score",        score_bar(result["lead_score"], color=color))
        prio = result["priority"]
        pc   = (GREEN if prio == "HOT" else YELLOW if prio == "WARM"
                else BLUE if prio == "COOL" else GRAY) if color else ""
        row("Priority Grade",    f"{(BOLD if color else '')}{pc}{result['lead_grade']} — {prio}{(RESET if color else '')}")
    lines.append("")

    # ── Loan options table ────────────────────────────────────────────────────
    hdr("💰  $0-DOWN LOAN OPTIONS")
    hr("─")
    hdr_row = f"  {'Loan Term':<18} {'APR':>6}  {'Monthly Pmt':>12}  {'Day-1 CF':>10}  {'25yr Savings':>13}"
    lines.append((BOLD if color else "") + hdr_row + (RESET if color else ""))
    hr("·")

    rec_years = result["recommended_option"]["years"]
    for opt in result["loan_options"]:
        pmt   = opt["monthly_payment_usd"]
        day1  = opt["day1_cashflow_usd"]
        yr25  = opt["total_saved_25yr_usd"]
        is_rec = opt["years"] == rec_years

        marker = (f"{GREEN}★ BEST{RESET} " if color and is_rec else
                  "★ BEST " if is_rec else "       ")
        cf_str = cf_color(day1, color)
        pmt_c  = (GREEN if is_rec else "") if color else ""
        yr25_c = (GREEN if yr25 > 0 else RED) if color else ""
        lines.append(
            f"  {marker}{opt['label']:<13} {opt['apr_pct']:>5.2f}%  "
            f"{pmt_c}${pmt:>10,.2f}{RESET if color and is_rec else ''}  "
            f"{cf_str:>20}  "
            f"{yr25_c}${yr25:>11,.0f}{RESET if color else ''}"
        )
    hr("·")
    lines.append(
        f"  {GRAY if color else ''}Day-1 Cash Flow = Monthly Savings − Monthly Loan Payment{RESET if color else ''}"
    )
    lines.append(f"  {GRAY if color else ''}Compared to ${result['monthly_bill_usd']:.0f}/mo current bill{RESET if color else ''}")
    lines.append("")

    # ── Bill escalation table ─────────────────────────────────────────────────
    hdr("📈  UTILITY BILL ESCALATION (3.5%/yr)")
    hr("─")
    lines.append(
        (BOLD if color else "") +
        f"  {'Year':<8} {'Monthly Bill':>13} {'Cumulative Paid':>17}" +
        (RESET if color else "")
    )
    hr("·")
    now_c = (GREEN if color else "")
    lines.append(f"  {'Now':<8} {now_c}${result['monthly_bill_usd']:>12,.2f}{RESET if color else ''}  {'(today)':>17}")
    for e in result["escalation_table"]:
        yr_c = (RED if e["year"] >= 10 else YELLOW if e["year"] >= 5 else "") if color else ""
        yr_label = f"Yr {e['year']}"
        lines.append(
            f"  {yr_label:<8} {yr_c}${e['bill_usd']:>12,.2f}{RESET if color else ''}  "
            f"${e['cumulative_usd']:>14,.0f}"
        )
    lines.append("")

    # ── Talking points ────────────────────────────────────────────────────────
    hdr("🗣️  CLOSING TALKING POINTS")
    hr("─")
    import textwrap
    for i, pt in enumerate(result["talking_points"], 1):
        wrapped = textwrap.fill(pt, width=60)
        first = True
        for line in wrapped.split("\n"):
            prefix = f"  {(YELLOW+BOLD if color else '')}{i}.{(RESET if color else '')} " if first else "     "
            lines.append(f"{prefix}{line}")
            first = False
        lines.append("")

    hr()
    mode_note = "Based on real Google Solar API data." if result["mode"] == "enriched" \
                else "Estimated — run with full address for real data."
    lines.append(f"  {GRAY if color else ''}{mode_note}{RESET if color else ''}")
    hr()

    return "\n".join(lines)


# ── CLI entry point ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Solar Financing Calculator — shows $0-down monthly payment vs current bill"
    )
    parser.add_argument("address", nargs="?", default="",
                        help="Street address to analyze (optional)")
    parser.add_argument("--bill",    type=float, default=175,
                        help="Monthly electric bill in dollars (default: 175)")
    parser.add_argument("--rate",    type=float, default=DEFAULT_UTILITY_RATE,
                        help="Utility rate in $/kWh (default: 0.145)")
    parser.add_argument("--state-credit", type=float, default=0.0,
                        help="State tax credit percentage, e.g. 0.10 for 10%% (default: 0)")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip API enrichment — bill estimate only")
    parser.add_argument("--json",    action="store_true", help="Output raw JSON")
    parser.add_argument("--no-color",action="store_true", help="Disable ANSI colors")

    args = parser.parse_args()
    color = not args.no_color

    lead = None
    if args.address and not args.no_enrich:
        from core.solar import enrich_lead
        if color:
            print(f"{CYAN}⚡ Enriching {args.address}...{RESET}")
        try:
            lead = enrich_lead(args.address)
        except Exception as e:
            if color:
                print(f"{YELLOW}⚠️  Could not enrich: {e} — running estimate mode{RESET}")

    result = calculate_financing(
        lead,
        monthly_bill=args.bill,
        utility_rate=args.rate,
        include_state_incentive=args.state_credit,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_report(result, color=color))


if __name__ == "__main__":
    main()
