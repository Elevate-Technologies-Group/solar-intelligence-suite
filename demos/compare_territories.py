#!/usr/bin/env python3
"""
compare_territories.py — Arizona Territory Leaderboard

Compares 3 Arizona zip codes (85234 Gilbert, 85374 Surprise, 85326 Buckeye)
and prints a ranked leaderboard with solar potential + lead quality metrics.

Usage:
    python demos/compare_territories.py
    python demos/compare_territories.py --zips 85001 85234 85374
    python demos/compare_territories.py --sample 8 --bill 200
"""
import sys, os, argparse, json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── ANSI colors ───────────────────────────────────────────────────────────────
RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
GREEN = "\033[32m"; YELLOW = "\033[33m"; CYAN = "\033[36m"; RED = "\033[31m"
BRIGHT_GREEN = "\033[92m"; BRIGHT_YELLOW = "\033[93m"; BRIGHT_CYAN = "\033[96m"
BRIGHT_WHITE = "\033[97m"; BRIGHT_RED = "\033[91m"; BRIGHT_MAGENTA = "\033[95m"
BG_GREEN = "\033[42m"; BG_YELLOW = "\033[43m"; BG_RED = "\033[41m"; BG_BLACK = "\033[40m"

WIDTH = 72

def c(text, *codes): return "".join(codes) + str(text) + RESET
def hr(ch="─", col=DIM): return c(ch * WIDTH, col)

METRO_NAMES = {
    "85234": "Gilbert, AZ",
    "85374": "Surprise, AZ",
    "85326": "Buckeye, AZ",
    "85001": "Phoenix (Downtown), AZ",
    "85018": "Phoenix (Arcadia), AZ",
    "85251": "Scottsdale, AZ",
    "85254": "Scottsdale North, AZ",
    "85203": "Mesa, AZ",
    "85224": "Chandler, AZ",
}

MEDAL = ["🥇", "🥈", "🥉"]

def grade_color(grade):
    if grade in ("A+", "A"): return BRIGHT_GREEN
    if grade == "B": return BRIGHT_YELLOW
    if grade == "C": return YELLOW
    return DIM

def priority_badge(priority):
    if priority == "HOT":  return c(" HOT  ", BG_RED, BRIGHT_WHITE, BOLD)
    if priority == "WARM": return c(" WARM ", BG_YELLOW, BRIGHT_WHITE, BOLD)
    return c(" COOL ", BG_BLACK, DIM)

def score_mini_bar(score, width=20):
    filled = int(score / 100 * width)
    empty  = width - filled
    if score >= 80:   col = BRIGHT_GREEN
    elif score >= 65: col = GREEN
    elif score >= 50: col = BRIGHT_YELLOW
    else:             col = YELLOW
    return c("█" * filled, col) + c("░" * empty, DIM)


def main():
    parser = argparse.ArgumentParser(description="Arizona territory solar leaderboard")
    parser.add_argument("--zips",   nargs="+", default=["85234", "85374", "85326"],
                        help="Zip codes to compare (default: 85234 85374 85326)")
    parser.add_argument("--sample", "-s", type=int, default=5,
                        help="Addresses to sample per zip (default: 5)")
    parser.add_argument("--bill",   "-b", type=float, default=185.0,
                        help="Avg monthly bill USD (default: 185)")
    args = parser.parse_args()

    from tools.territory import multi_zip_comparison

    print()
    print(c("═" * WIDTH, BRIGHT_CYAN))
    print(c(f"  ☀  ARIZONA SOLAR TERRITORY LEADERBOARD  ☀", BRIGHT_YELLOW, BOLD).center(WIDTH + 20))
    print(c(f"  Zip Codes: {', '.join(args.zips)}  |  Sample: {args.sample}/zip  |  Avg Bill: ${args.bill:.0f}", DIM))
    print(c("═" * WIDTH, BRIGHT_CYAN))
    print()
    print(c("  Scanning territories… (cached results load instantly)", DIM))
    print()

    results = multi_zip_comparison(args.zips, sample_size=args.sample)
    ranked  = results.get("ranked", [])

    if not ranked:
        print(c("  ❌ No results returned. Check API key and network.", BRIGHT_RED))
        sys.exit(1)

    # ── LEADERBOARD ───────────────────────────────────────────────────────────
    print(c("  RANKED TERRITORY LEADERBOARD", BOLD, BRIGHT_WHITE))
    print(hr())
    print()

    for i, territory in enumerate(ranked):
        zip_code  = territory.get("zip_code", "?")
        metro     = METRO_NAMES.get(zip_code, f"ZIP {zip_code}")
        grade     = territory.get("territory_grade", "?")
        hot       = territory.get("hot_leads", 0)
        warm      = territory.get("warm_leads", 0)
        total     = territory.get("leads_enriched", 0)
        avg_score = territory.get("avg_lead_score", 0)
        avg_save  = territory.get("avg_annual_savings_usd", 0)
        avg_sun   = territory.get("avg_sunshine_hours", 0)
        avg_pay   = territory.get("avg_payback_years", 0)
        top_score = territory.get("top_lead_score", 0)

        medal = MEDAL[i] if i < 3 else f"  #{i+1}"

        print(f"  {medal}  {c(metro, BOLD, BRIGHT_WHITE)}  {c(f'({zip_code})', DIM)}")
        print(f"       Territory Grade: {c(grade, grade_color(grade), BOLD)}   "
              f"Avg Score: [{score_mini_bar(int(avg_score))}] {c(f'{avg_score:.1f}', BRIGHT_WHITE)}/100")
        print(f"       Hot Leads: {c(hot, BRIGHT_RED, BOLD)}/{total}   "
              f"Warm: {c(warm, BRIGHT_YELLOW)}   "
              f"Avg Savings: {c(f'${avg_save:,.0f}/yr', BRIGHT_GREEN, BOLD)}")
        print(f"       Avg Sunshine: {c(f'{avg_sun:,.0f} hrs/yr', BRIGHT_YELLOW)}   "
              f"Avg Payback: {c(f'{avg_pay:.1f} yrs', CYAN)}   "
              f"Top Lead Score: {c(top_score, BRIGHT_GREEN)}/100")
        print()

        # Show top 3 prospects for the top zip
        if i == 0 and territory.get("top_prospects"):
            print(c("       ─── TOP PROSPECTS ───────────────────────────────────", DIM))
            for j, p in enumerate(territory["top_prospects"][:3], 1):
                addr  = (p.get("address") or "")[:52]
                pg    = p.get("lead_grade", "?")
                ps    = p.get("lead_score", 0)
                psave = p.get("annual_savings_yr1_usd", 0)
                ppay  = p.get("payback_years", 0)
                ppr   = p.get("priority", "")
                print(f"       {j}. {c(f'[{pg}]', grade_color(pg), BOLD)} "
                      f"{priority_badge(ppr)} "
                      f"Score:{c(ps, BRIGHT_WHITE)}/100  "
                      f"Save:{c(f'${psave:,.0f}', BRIGHT_GREEN)}/yr  "
                      f"Payback:{c(ppay, CYAN)}yr")
                print(f"          {c(addr, DIM)}")
            print()

        print(hr("·", DIM))
        print()

    # ── WINNER SUMMARY ────────────────────────────────────────────────────────
    if ranked:
        winner = ranked[0]
        winner_zip   = winner.get("zip_code", "?")
        winner_metro = METRO_NAMES.get(winner_zip, f"ZIP {winner_zip}")
        winner_grade = winner.get("territory_grade", "?")
        winner_hot   = winner.get("hot_leads", 0)
        winner_save  = winner.get("avg_annual_savings_usd", 0)

        print(c(f"  🏆 WINNER: {winner_metro} ({winner_zip})", BRIGHT_YELLOW, BOLD))
        print(c(f"     Grade {winner_grade} territory — {winner_hot} HOT leads — "
                f"avg ${winner_save:,.0f}/yr savings", DIM))
        print()

    # ── Save JSON results ─────────────────────────────────────────────────────
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(cache_dir, f"territory_compare_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    print(hr("═", BRIGHT_CYAN))
    print(c(f"  Full results saved → cache/territory_compare_{ts}.json", DIM))
    print(hr("═", BRIGHT_CYAN))
    print()


if __name__ == "__main__":
    main()
