#!/usr/bin/env python3
"""
daily_digest.py — Solar Intelligence Suite Daily Digest Generator

Reads all cached territory scans and enriched leads from the cache folder,
summarizes key stats, formats output as a Discord-ready message,
and saves to /root/solar-tools/cache/daily_digest.txt

Usage:
    python scripts/daily_digest.py
    python scripts/daily_digest.py --output /path/to/output.txt
    python scripts/daily_digest.py --discord-only     # prints Discord message only
    python scripts/daily_digest.py --json             # output JSON summary
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

# ── path setup ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "cache"
DEFAULT_OUTPUT = CACHE_DIR / "daily_digest.txt"


# ─── cache reader ─────────────────────────────────────────────────────────────

def load_cache_files():
    """Load all JSON cache files, categorize them."""
    territory_files = []
    individual_leads = []
    territory_compare = []

    for f in sorted(CACHE_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
        except Exception:
            continue

        name = f.name

        # Territory scan files (named territory_XXXXX.json)
        if name.startswith("territory_") and not name.startswith("territory_compare"):
            territory_files.append((name, data))

        # Territory comparison files
        elif name.startswith("territory_compare"):
            territory_compare.append((name, data))

        # Individual enriched lead files — look for lead_score key
        elif "lead_score" in data and "address" in data:
            individual_leads.append(data)

    return territory_files, individual_leads, territory_compare


def extract_all_leads(territory_files, individual_leads):
    """Extract every enriched lead from all sources, dedup by address."""
    seen = {}

    # From territory scans
    for fname, t in territory_files:
        for lead in t.get("prospects", []):
            addr = lead.get("address", "")
            if addr and addr not in seen:
                seen[addr] = lead

    # From individual lead cache files
    for lead in individual_leads:
        addr = lead.get("address", "")
        if addr and addr not in seen:
            seen[addr] = lead

    return list(seen.values())


def summarize_territories(territory_files):
    """Build a summary list of scanned territories."""
    territories = []
    for fname, t in territory_files:
        if not t or "zip_code" not in t:
            continue
        territories.append({
            "zip": t.get("zip_code", "?"),
            "center": t.get("center", "Unknown"),
            "grade": t.get("territory_grade", "?"),
            "addresses_scanned": t.get("addresses_scanned", 0),
            "leads_enriched": t.get("leads_enriched", 0),
            "hot_leads": t.get("hot_leads", 0),
            "avg_score": t.get("avg_lead_score", 0),
            "avg_savings": t.get("avg_annual_savings_usd", 0),
            "avg_payback": t.get("avg_payback_years", 0),
        })
    # Sort by avg_score descending
    territories.sort(key=lambda x: x["avg_score"], reverse=True)
    return territories


def compute_top_leads(all_leads, n=5):
    """Return top N leads by lead_score."""
    valid = [l for l in all_leads if isinstance(l.get("lead_score"), (int, float)) and not l.get("error")]
    return sorted(valid, key=lambda x: x["lead_score"], reverse=True)[:n]


def compute_stats(all_leads):
    """Aggregate stats across all enriched leads."""
    valid = [l for l in all_leads if not l.get("error") and isinstance(l.get("lead_score"), (int, float))]
    if not valid:
        return {}

    hot = [l for l in valid if l.get("priority") == "HOT"]
    warm = [l for l in valid if l.get("priority") == "WARM"]
    scores = [l["lead_score"] for l in valid]
    savings = [l.get("annual_savings_yr1_usd", 0) for l in valid if l.get("annual_savings_yr1_usd")]
    paybacks = [l.get("payback_years", 0) for l in valid if l.get("payback_years")]
    sunshine = [l.get("sunshine_hours_per_year", 0) for l in valid if l.get("sunshine_hours_per_year")]

    return {
        "total_leads": len(valid),
        "hot_leads": len(hot),
        "warm_leads": len(warm),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "max_score": max(scores) if scores else 0,
        "avg_annual_savings": round(sum(savings) / len(savings)) if savings else 0,
        "max_annual_savings": max(savings) if savings else 0,
        "avg_payback_years": round(sum(paybacks) / len(paybacks), 1) if paybacks else 0,
        "avg_sunshine_hours": round(sum(sunshine) / len(sunshine)) if sunshine else 0,
        "total_annual_savings_pipeline": round(sum(savings)),
    }


# ─── formatters ───────────────────────────────────────────────────────────────

def _grade_emoji(grade):
    return {"HOT": "🔥", "WARM": "☀️", "COOL": "🌤️", "LOW": "❄️"}.get(grade, "📍")


def _score_bar(score, width=12):
    """Simple ASCII bar for Discord."""
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def format_discord_message(stats, territories, top_leads, run_ts):
    """
    Format a Discord-ready digest message.
    Stays under 2000 chars so it posts cleanly as a single Discord message.
    """
    ts_str = run_ts.strftime("%a %b %d, %Y · %I:%M %p UTC")
    lines = []

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("☀️  **SOLAR INTELLIGENCE — DAILY DIGEST**")
    lines.append(f"📅  {ts_str}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    if stats:
        lines.append(f"**📊 PIPELINE SNAPSHOT**")
        lines.append(f"  🔥 HOT leads: **{stats['hot_leads']}**  |  ☀️ WARM: **{stats['warm_leads']}**  |  Total: **{stats['total_leads']}**")
        lines.append(f"  📈 Avg score: **{stats['avg_score']}/100**  |  Peak: **{stats['max_score']}/100**")
        lines.append(f"  💰 Avg yr-1 savings: **${stats['avg_annual_savings']:,}**  |  Pipeline value: **${stats['total_annual_savings_pipeline']:,}**")
        lines.append(f"  ⏱️  Avg payback: **{stats['avg_payback_years']} yrs**  |  ☀️ Avg sunshine: **{stats['avg_sunshine_hours']:,} hrs/yr**")
        lines.append("")

    if territories:
        lines.append("**🗺️ TERRITORIES SCANNED**")
        for t in territories[:5]:  # cap at 5 for Discord
            emoji = _grade_emoji(t["grade"])
            city = t["center"].split(",")[0] if t["center"] else t["zip"]
            lines.append(
                f"  {emoji} **{city} ({t['zip']})** — avg {t['avg_score']:.0f}/100 · "
                f"{t['hot_leads']} HOT · ${t['avg_savings']:,}/yr avg savings"
            )
        lines.append("")

    if top_leads:
        lines.append("**🏆 TOP PROSPECTS**")
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, lead in enumerate(top_leads[:5]):
            medal = medals[i] if i < len(medals) else "•"
            addr_short = lead["address"].replace(", USA", "").replace(", United States", "")
            score = lead.get("lead_score", 0)
            savings = lead.get("annual_savings_yr1_usd", 0)
            grade = lead.get("lead_grade", "?")
            bar = _score_bar(score, 8)
            lines.append(f"  {medal} `[{grade}] {bar} {score}/100` — {addr_short}  💰 ${savings:,.0f}/yr")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🤖 *Solar Intelligence Suite — Automated Digest*")
    lines.append(f"🔗 Dashboard: http://localhost:8765")

    return "\n".join(lines)


def format_full_report(stats, territories, top_leads, run_ts):
    """
    Full detailed text report saved to file.
    """
    ts_str = run_ts.strftime("%Y-%m-%d %H:%M UTC")
    width = 72
    border = "═" * width
    thin = "─" * width

    lines = []
    lines.append(border)
    lines.append("  ☀  SOLAR INTELLIGENCE SUITE — DAILY DIGEST REPORT")
    lines.append(f"  Generated: {ts_str}")
    lines.append(border)
    lines.append("")

    # ── Pipeline Stats ──────────────────────────────────────────────────────
    lines.append("  PIPELINE SNAPSHOT")
    lines.append(thin)
    if stats:
        lines.append(f"  Total Enriched Leads  : {stats['total_leads']}")
        lines.append(f"  HOT Leads (A+/A)      : {stats['hot_leads']}  🔥")
        lines.append(f"  WARM Leads (B)        : {stats['warm_leads']}  ☀️")
        lines.append(f"  Average Lead Score    : {stats['avg_score']}/100")
        lines.append(f"  Highest Score         : {stats['max_score']}/100")
        lines.append(f"  Avg Year-1 Savings    : ${stats['avg_annual_savings']:,}")
        lines.append(f"  Max Year-1 Savings    : ${stats['max_annual_savings']:,}")
        lines.append(f"  Total Pipeline Value  : ${stats['total_annual_savings_pipeline']:,}/yr")
        lines.append(f"  Avg Payback Period    : {stats['avg_payback_years']} years")
        lines.append(f"  Avg Sunshine Hours    : {stats['avg_sunshine_hours']:,} hrs/year")
    else:
        lines.append("  No enriched leads found in cache.")
    lines.append("")

    # ── Territory Leaderboard ───────────────────────────────────────────────
    lines.append("  SCANNED TERRITORIES")
    lines.append(thin)
    if territories:
        lines.append(f"  {'RANK':<5} {'ZIP':<8} {'CITY':<20} {'GRADE':<7} {'AVG SCORE':<12} {'HOT':<6} {'AVG SAVINGS'}")
        lines.append(f"  {'─'*4:<5} {'─'*5:<8} {'─'*18:<20} {'─'*5:<7} {'─'*9:<12} {'─'*3:<6} {'─'*10}")
        medals_text = ["🥇 1st", "🥈 2nd", "🥉 3rd", "  4th", "  5th"]
        for i, t in enumerate(territories):
            rank = medals_text[i] if i < len(medals_text) else f"  {i+1}th"
            city = t["center"].split(",")[0][:18] if t["center"] else t["zip"]
            lines.append(
                f"  {rank:<6} {t['zip']:<8} {city:<20} {t['grade']:<7} "
                f"{t['avg_score']:<12.1f} {t['hot_leads']:<6} ${t['avg_savings']:,}/yr"
            )
    else:
        lines.append("  No territory scans found in cache.")
    lines.append("")

    # ── Top Prospects ───────────────────────────────────────────────────────
    lines.append("  TOP PROSPECTS — READY TO CONTACT")
    lines.append(thin)
    if top_leads:
        for i, lead in enumerate(top_leads, 1):
            addr = lead.get("address", "Unknown").replace(", USA", "")
            score = lead.get("lead_score", 0)
            grade = lead.get("lead_grade", "?")
            priority = lead.get("priority", "?")
            bill = lead.get("monthly_bill_usd", 0)
            savings = lead.get("annual_savings_yr1_usd", 0)
            lifetime = lead.get("lifetime_savings_usd", 0)
            payback = lead.get("payback_years", 0)
            sunshine = lead.get("sunshine_hours_per_year", 0)
            segments = lead.get("roof_segments", 0)
            imagery = lead.get("imagery_date", {})
            img_year = imagery.get("year", "N/A") if isinstance(imagery, dict) else "N/A"

            bar_filled = round(score / 100 * 20)
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            lines.append(f"  #{i} [{grade}] {priority}")
            lines.append(f"     {addr}")
            lines.append(f"     Score   : [{bar}] {score}/100")
            lines.append(f"     Bill    : ${bill:.0f}/mo  →  ${savings:,.0f}/yr savings  →  ${lifetime:,.0f} lifetime")
            lines.append(f"     Payback : {payback} yrs  |  Sunshine: {sunshine:,} hrs/yr  |  Roof: {segments} segments")
            lines.append(f"     Imagery : {img_year}")
            if lead.get("talking_points"):
                lines.append(f"     Talking Points:")
                for pt in lead["talking_points"][:3]:
                    lines.append(f"       • {pt}")
            lines.append("")
    else:
        lines.append("  No prospects found.")

    lines.append(border)
    lines.append("  END OF DAILY DIGEST")
    lines.append(border)

    return "\n".join(lines)


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Solar Intelligence Suite Daily Digest")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output file path")
    parser.add_argument("--discord-only", action="store_true", help="Print Discord message only (no file)")
    parser.add_argument("--json", action="store_true", help="Output JSON summary instead")
    parser.add_argument("--print", action="store_true", help="Also print full report to stdout")
    args = parser.parse_args()

    run_ts = datetime.now(timezone.utc)

    # ── Load cache ────────────────────────────────────────────────────────────
    territory_files, individual_leads, territory_compare = load_cache_files()
    all_leads = extract_all_leads(territory_files, individual_leads)
    territories = summarize_territories(territory_files)
    top_leads = compute_top_leads(all_leads, n=5)
    stats = compute_stats(all_leads)

    if args.json:
        summary = {
            "generated_at": run_ts.isoformat(),
            "stats": stats,
            "territories": territories,
            "top_leads": [
                {
                    "address": l.get("address"),
                    "score": l.get("lead_score"),
                    "grade": l.get("lead_grade"),
                    "priority": l.get("priority"),
                    "annual_savings": l.get("annual_savings_yr1_usd"),
                    "payback_years": l.get("payback_years"),
                }
                for l in top_leads
            ],
        }
        print(json.dumps(summary, indent=2))
        return

    # ── Build Discord message ─────────────────────────────────────────────────
    discord_msg = format_discord_message(stats, territories, top_leads, run_ts)

    if args.discord_only:
        print(discord_msg)
        return

    # ── Build full report ─────────────────────────────────────────────────────
    full_report = format_full_report(stats, territories, top_leads, run_ts)

    # ── Assemble file content ─────────────────────────────────────────────────
    separator = "\n\n" + "─" * 72 + "\n"
    file_content = full_report + separator
    file_content += "DISCORD-READY MESSAGE (copy/paste):\n"
    file_content += "─" * 72 + "\n\n"
    file_content += discord_msg + "\n"

    # ── Write to file ─────────────────────────────────────────────────────────
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(file_content)

    if args.print:
        print(full_report)
        print("\n" + "=" * 72)
        print("DISCORD MESSAGE:")
        print("=" * 72)
        print(discord_msg)

    # Always print summary line
    print(f"✅ Daily digest saved to: {output_path}")
    print(f"   Territories: {len(territories)} | Leads: {stats.get('total_leads', 0)} | HOT: {stats.get('hot_leads', 0)} | WARM: {stats.get('warm_leads', 0)}")
    print(f"   Avg score: {stats.get('avg_score', 0)}/100 | Pipeline value: ${stats.get('total_annual_savings_pipeline', 0):,}/yr")

    # ── Discord: post daily digest embed (if DISCORD_WEBHOOK_URL is set) ─────
    try:
        from integrations.discord_alerts import notify_daily_digest
        # Build stats dict for the Discord embed
        discord_stats = {
            "total_leads":           stats.get("total_leads", 0),
            "hot_leads":             stats.get("hot_leads", 0),
            "warm_leads":            stats.get("warm_leads", 0),
            "avg_lead_score":        stats.get("avg_score", 0.0),
            "total_pipeline_value":  stats.get("total_annual_savings_pipeline", 0),
            "avg_annual_savings":    stats.get("avg_annual_savings", 0.0),
            "territory_count":       len(territories),
            "top_lead_address":      top_leads[0].get("address") if top_leads else "",
            "top_lead_score":        top_leads[0].get("lead_score") if top_leads else 0,
            "territory_rankings": [
                {
                    "zip_code":        t.get("zip_code", "?"),
                    "city":            t.get("city", ""),
                    "territory_grade": t.get("territory_grade", "?"),
                    "avg_lead_score":  t.get("avg_lead_score", 0),
                    "hot_leads":       t.get("hot_leads", 0),
                }
                for t in territories
            ],
        }
        ok = notify_daily_digest(stats=discord_stats)
        if ok:
            print(f"   📣 Discord daily digest posted")
    except Exception as _e:
        pass  # Discord is optional


if __name__ == "__main__":
    main()
