#!/usr/bin/env python3
"""
solar_enrich.py — Beautiful terminal solar lead report

Usage:
    python solar_enrich.py "1234 W Main St, Phoenix, AZ 85001"
    python solar_enrich.py "1234 W Main St, Phoenix, AZ" --bill 225
    python solar_enrich.py "1234 W Main St, Phoenix, AZ" --bill 225 --rate 0.16

Requires GOOGLE_MAPS_API_KEY in environment.
"""
import sys, os, argparse, textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── ANSI color helpers ───────────────────────────────────────────────────────

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"

BLACK   = "\033[30m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
WHITE   = "\033[37m"

BRIGHT_RED    = "\033[91m"
BRIGHT_GREEN  = "\033[92m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_BLUE   = "\033[94m"
BRIGHT_MAGENTA= "\033[95m"
BRIGHT_CYAN   = "\033[96m"
BRIGHT_WHITE  = "\033[97m"

BG_BLUE   = "\033[44m"
BG_GREEN  = "\033[42m"
BG_RED    = "\033[41m"
BG_YELLOW = "\033[43m"
BG_BLACK  = "\033[40m"

WIDTH = 70


def c(text, *codes):
    return "".join(codes) + str(text) + RESET


def hr(char="─", color=DIM):
    return c(char * WIDTH, color)


def header_bar(title: str, bg=BG_BLUE, fg=BRIGHT_WHITE):
    padding = WIDTH - len(title) - 4
    left  = padding // 2
    right = padding - left
    return c(f"  {' ' * left}{title}{' ' * right}  ", bg, fg, BOLD)


def score_bar(score: int, width: int = 40) -> str:
    """Render a colored ASCII progress bar for a 0-100 score."""
    filled = int(score / 100 * width)
    empty  = width - filled

    if score >= 80:   bar_color = BRIGHT_GREEN
    elif score >= 65: bar_color = GREEN
    elif score >= 50: bar_color = BRIGHT_YELLOW
    elif score >= 35: bar_color = YELLOW
    else:             bar_color = BRIGHT_RED

    bar = c("█" * filled, bar_color) + c("░" * empty, DIM)
    return f"[{bar}] {c(str(score), BOLD, bar_color)}/100"


def grade_badge(grade: str, priority: str) -> str:
    if priority == "HOT":
        bg = BG_RED
    elif priority == "WARM":
        bg = BG_YELLOW
    else:
        bg = BG_BLACK
    return c(f" {grade} ", bg, BRIGHT_WHITE, BOLD) + " " + c(f"{priority}", BOLD,
        BRIGHT_RED if priority == "HOT" else (BRIGHT_YELLOW if priority == "WARM" else DIM))


def section(title: str):
    print()
    print(c(f" ◆ {title}", BRIGHT_CYAN, BOLD))
    print(hr("─", DIM))


def row(label: str, value: str, label_color=DIM, value_color=BRIGHT_WHITE):
    label_str = c(f"  {label:<28}", label_color)
    value_str = c(value, value_color)
    print(f"{label_str} {value_str}")


def main():
    parser = argparse.ArgumentParser(
        description="Solar lead enrichment — beautiful terminal report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python solar_enrich.py "1234 W Main St, Gilbert, AZ 85234"
          python solar_enrich.py "1234 W Main St, Gilbert, AZ" --bill 225
          python solar_enrich.py "1234 W Main St, Gilbert, AZ" --bill 300 --rate 0.155
        """)
    )
    parser.add_argument("address", help="Full street address to analyze")
    parser.add_argument("--bill",  "-b", type=float, default=175.0,
                        help="Monthly electric bill in USD (default: 175)")
    parser.add_argument("--rate",  "-r", type=float, default=0.14,
                        help="Utility rate $/kWh (default: 0.14)")
    parser.add_argument("--json",  "-j", action="store_true",
                        help="Output raw JSON instead of formatted report")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable colored output")
    args = parser.parse_args()

    # Disable color if requested or if not a TTY
    if args.no_color or not sys.stdout.isatty():
        for name in ["RESET","BOLD","DIM","BLACK","RED","GREEN","YELLOW","BLUE",
                     "MAGENTA","CYAN","WHITE","BRIGHT_RED","BRIGHT_GREEN",
                     "BRIGHT_YELLOW","BRIGHT_BLUE","BRIGHT_MAGENTA","BRIGHT_CYAN",
                     "BRIGHT_WHITE","BG_BLUE","BG_GREEN","BG_RED","BG_YELLOW","BG_BLACK"]:
            globals()[name] = ""

    # ── Spinner / loading message ────────────────────────────────────────────
    print(c("\n⚡ Solar Intelligence Suite", BRIGHT_YELLOW, BOLD))
    print(c(f"   Analyzing: {args.address}", DIM))
    print(c(f"   Monthly bill: ${args.bill:.0f}  |  Rate: ${args.rate:.3f}/kWh\n", DIM))

    # ── Run enrichment ───────────────────────────────────────────────────────
    from core.solar import enrich_lead
    lead = enrich_lead(args.address, monthly_bill=args.bill, utility_rate=args.rate)

    if "error" in lead:
        print(c(f"\n❌ ERROR: {lead['error']}", BRIGHT_RED, BOLD))
        sys.exit(1)

    # ── JSON mode ────────────────────────────────────────────────────────────
    if args.json:
        import json
        print(json.dumps(lead, indent=2))
        return

    # ════════════════════════════════════════════════════════════════════════
    # REPORT HEADER
    # ════════════════════════════════════════════════════════════════════════
    print(header_bar("☀  SOLAR LEAD INTELLIGENCE REPORT  ☀"))
    print()

    # Address + grade
    addr_short = lead["address"][:60] + ("..." if len(lead["address"]) > 60 else "")
    print(f"  {c(addr_short, BOLD, BRIGHT_WHITE)}")
    print(f"  {c(lead.get('city',''), CYAN)}, {c(lead.get('state',''), CYAN)}  {c(lead.get('postal_code',''), DIM)}")
    print()

    # Lead grade + score bar
    grade_str = grade_badge(lead["lead_grade"], lead["priority"])
    print(f"  Lead Grade   {grade_str}")
    print(f"  Score        {score_bar(lead['lead_score'])}")

    # Score breakdown
    bd = lead.get("score_breakdown", {})
    print(f"  {c('Breakdown', DIM)}  ", end="")
    parts = []
    for k, v in bd.items():
        parts.append(c(f"{k}:{v}", DIM))
    print("  ".join(parts))

    # ════════════════════════════════════════════════════════════════════════
    # ROOF & SOLAR ANALYSIS
    # ════════════════════════════════════════════════════════════════════════
    section("ROOF & SOLAR ANALYSIS")

    imagery = lead.get("imagery_date", {})
    if isinstance(imagery, dict):
        img_str = f"{imagery.get('year','?')}-{imagery.get('month','?'):02d}" if imagery.get('year') else "N/A"
    else:
        img_str = str(imagery)

    row("Sunshine hrs/year",    f"{lead.get('sunshine_hours_per_year',0):,} hrs  ☀")
    row("Roof segments",        str(lead.get("roof_segments", 0)))
    row("Max panels possible",  str(lead.get("max_panels_possible", 0)))
    row("Panels recommended",   str(lead.get("panels_recommended", 0)))
    row("System size",          f"{lead.get('system_size_kw', 0)} kW",        value_color=BRIGHT_CYAN)
    row("Annual production",    f"{lead.get('annual_kwh_produced',0):,} kWh")
    row("Annual usage needed",  f"{lead.get('annual_kwh_needed',0):,} kWh")
    row("Energy offset",        f"{lead.get('offset_pct',0)}%",
        value_color=BRIGHT_GREEN if lead.get('offset_pct',0) >= 90 else BRIGHT_YELLOW)
    row("Imagery quality",      lead.get("imagery_quality", "?"))
    row("Imagery date",         img_str)

    # ════════════════════════════════════════════════════════════════════════
    # FINANCIAL PROJECTIONS
    # ════════════════════════════════════════════════════════════════════════
    section("FINANCIAL PROJECTIONS")

    row("Current monthly bill", f"${args.bill:,.0f}/mo",  value_color=BRIGHT_RED)
    row("Gross system cost",    f"${lead.get('gross_cost_usd',0):,.0f}")
    row("Federal ITC (30%)",    f"- ${lead.get('federal_itc_usd',0):,.0f}",  value_color=BRIGHT_GREEN)
    row("Net investment",       f"${lead.get('net_cost_usd',0):,.0f}",        value_color=BRIGHT_WHITE)
    row("Est. monthly loan*",   f"~${lead.get('net_cost_usd',0)/240:,.0f}/mo  (20yr @ 6%)", value_color=DIM)
    print()
    row("Year 1 savings",       f"${lead.get('annual_savings_yr1_usd',0):,.0f}",  value_color=BRIGHT_GREEN)
    row("Payback period",       f"{lead.get('payback_years',0)} years",
        value_color=BRIGHT_GREEN if lead.get('payback_years',99) <= 8 else YELLOW)
    row("25-year ROI",          f"{lead.get('roi_25yr_pct',0)}%",  value_color=BRIGHT_GREEN)
    row("Lifetime savings",     f"${lead.get('lifetime_savings_usd',0):,.0f}",  value_color=BRIGHT_GREEN)

    # ════════════════════════════════════════════════════════════════════════
    # ENVIRONMENTAL IMPACT
    # ════════════════════════════════════════════════════════════════════════
    section("ENVIRONMENTAL IMPACT")
    row("CO₂ offset per year",  f"{lead.get('co2_offset_lbs_per_year',0):,.0f} lbs")
    row("Equivalent trees",     f"{lead.get('trees_equivalent_per_year',0):.1f} trees planted/year",
        value_color=BRIGHT_GREEN)

    # ════════════════════════════════════════════════════════════════════════
    # REP TALKING POINTS
    # ════════════════════════════════════════════════════════════════════════
    section("REP TALKING POINTS")
    for pt in lead.get("talking_points", []):
        # Wrap long lines
        wrapped = textwrap.fill(pt, width=WIDTH - 4, subsequent_indent="       ")
        print(f"  {c(wrapped, BRIGHT_WHITE)}")
        print()

    # ════════════════════════════════════════════════════════════════════════
    # FOOTER
    # ════════════════════════════════════════════════════════════════════════
    print(hr("═", BRIGHT_BLUE))
    print(c(f"  Data: Google Solar API  |  Scores: proprietary algorithm  |  Solar Intelligence Suite", DIM))
    print(hr("═", BRIGHT_BLUE))
    print()


if __name__ == "__main__":
    main()
