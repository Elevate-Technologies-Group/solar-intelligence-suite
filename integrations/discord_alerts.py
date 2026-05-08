#!/usr/bin/env python3
"""
discord_alerts.py — Discord Webhook Integration for Solar Intelligence Suite

Sends rich embeds to a Discord channel when HOT leads are found,
territory scans complete, or daily digests are ready.

Reads DISCORD_WEBHOOK_URL from environment.
Gracefully skips (no-op) if not set — no crashes, no noise.

Usage:
    from integrations.discord_alerts import (
        notify_hot_lead,
        notify_batch_results,
        notify_territory_scan,
        notify_daily_digest,
        post_message,
    )

    # Single HOT lead alert
    notify_hot_lead(lead, source="batch_enrich")

    # Batch result summary
    notify_batch_results(results_list, source_file="leads.csv")

    # Territory scan summary
    notify_territory_scan(territory_data)

    # Daily digest post
    notify_daily_digest(digest_text, stats_dict)

    # Raw message
    post_message("Hello from Solar Intelligence Suite!")

Standalone test:
    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... python integrations/discord_alerts.py --test
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Config ────────────────────────────────────────────────────────────────────

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

# Color codes for Discord embeds (decimal)
COLOR_HOT    = 0xFF4500   # Orange-red
COLOR_WARM   = 0xFFA500   # Orange
COLOR_COOL   = 0x00BFFF   # Sky blue
COLOR_LOW    = 0x808080   # Grey
COLOR_GREEN  = 0x00C851   # Green (success / digest)
COLOR_PURPLE = 0x7B2FBE   # Purple (territory)
COLOR_GOLD   = 0xFFD700   # Gold (top rank)

SUITE_ICON = "https://i.imgur.com/solarbot.png"   # fallback icon


# ── Core send function ────────────────────────────────────────────────────────

def _send(payload: dict, silent_if_no_webhook: bool = True) -> bool:
    """
    POST a Discord webhook payload.
    Returns True on success, False on failure.
    Skips silently if DISCORD_WEBHOOK_URL is not set (unless silent=False).
    """
    url = WEBHOOK_URL or os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        if not silent_if_no_webhook:
            print("⚠️  DISCORD_WEBHOOK_URL not set — skipping Discord notification")
        return False

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            return True
        else:
            print(f"⚠️  Discord webhook returned {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"⚠️  Discord webhook error: {e}")
        return False


def post_message(text: str) -> bool:
    """Send a plain text message to Discord."""
    return _send({"content": text})


# ── Grade helpers ─────────────────────────────────────────────────────────────

def _grade_color(grade: str) -> int:
    g = (grade or "").upper()
    if g in ("A+", "A"):  return COLOR_HOT
    if g == "B":           return COLOR_WARM
    if g == "C":           return COLOR_COOL
    return COLOR_LOW


def _priority_emoji(priority: str) -> str:
    p = (priority or "").upper()
    if p == "HOT":   return "🔥"
    if p == "WARM":  return "☀️"
    if p == "COOL":  return "❄️"
    return "📋"


def _score_bar(score: float, width: int = 15) -> str:
    """Mini ASCII score bar for embed fields."""
    filled = int(round((score / 100) * width))
    return "█" * filled + "░" * (width - filled) + f"  {score:.0f}/100"


# ── Lead alert ────────────────────────────────────────────────────────────────

def notify_hot_lead(lead: dict, source: str = "solar_enrich", min_grade: str = "B") -> bool:
    """
    Send a Discord embed for a single enriched lead.

    Only fires for leads at or above `min_grade` (default: B = WARM+).
    HOT leads get an @here ping.
    """
    if not lead or "error" in lead:
        return False

    grade    = (lead.get("lead_grade") or "D").upper()
    priority = (lead.get("priority") or "LOW").upper()

    # Grade filter
    grade_rank = {"A+": 5, "A": 4, "B": 3, "C": 2, "D": 1}
    min_rank   = grade_rank.get(min_grade.upper(), 3)
    if grade_rank.get(grade, 1) < min_rank:
        return False

    score    = lead.get("lead_score", 0)
    address  = lead.get("formatted_address") or lead.get("address", "Unknown address")
    bill     = lead.get("monthly_bill_usd", 0)
    savings  = lead.get("annual_savings_yr1_usd", 0)
    lifetime = lead.get("lifetime_savings_usd", 0)
    payback  = lead.get("payback_years", 0)
    system   = lead.get("system_size_kw", 0)
    panels   = lead.get("panels_recommended", 0)
    sunshine = lead.get("sunshine_hours_per_year", 0)
    net_cost = lead.get("net_cost_usd", 0)
    segments = lead.get("roof_segments", 0)
    imagery  = lead.get("imagery_date", "")

    # Talking points → first 2 only
    tps = lead.get("talking_points", [])
    tp_text = "\n".join(f"• {t}" for t in tps[:2]) if tps else "—"

    emoji = _priority_emoji(priority)
    color = _grade_color(grade)

    # Ping on HOT
    content = f"@here  **{emoji} HOT LEAD DETECTED**" if priority == "HOT" else f"{emoji} New {priority} lead found"

    # Score breakdown
    breakdown = lead.get("score_breakdown", {})
    breakdown_lines = []
    for k, v in list(breakdown.items())[:6]:
        label = k.replace("_", " ").title()
        breakdown_lines.append(f"`{label}` — **{v}**")
    breakdown_text = "\n".join(breakdown_lines) if breakdown_lines else "—"

    embed = {
        "title": f"{emoji} [{grade}] {priority} — {address}",
        "description": f"**Score:** `{_score_bar(score)}`\n\nSource: `{source}`",
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Solar Intelligence Suite"},
        "fields": [
            {
                "name": "💰 Financials",
                "value": (
                    f"Monthly Bill: **${bill:.0f}/mo**\n"
                    f"Year-1 Savings: **${savings:,.0f}**\n"
                    f"Lifetime Savings: **${lifetime:,.0f}**\n"
                    f"Net Cost (after ITC): **${net_cost:,.0f}**\n"
                    f"Payback: **{payback:.1f} yrs**"
                ),
                "inline": True,
            },
            {
                "name": "🏠 Roof / Solar",
                "value": (
                    f"System Size: **{system:.1f} kW**\n"
                    f"Panels: **{panels}**\n"
                    f"Roof Segments: **{segments}**\n"
                    f"Sunshine: **{sunshine:,.0f} hrs/yr**\n"
                    f"Imagery: **{imagery or 'unknown'}**"
                ),
                "inline": True,
            },
            {
                "name": "🗣️ Talking Points",
                "value": tp_text,
                "inline": False,
            },
            {
                "name": "📊 Score Breakdown",
                "value": breakdown_text,
                "inline": False,
            },
        ],
    }

    return _send({"content": content, "embeds": [embed]})


# ── Batch results summary ─────────────────────────────────────────────────────

def notify_batch_results(results: list, source_file: str = "batch", hot_only: bool = False) -> bool:
    """
    Send a summary embed after a batch enrichment run.
    Optionally also sends individual embeds for each HOT lead.
    """
    if not results:
        return False

    total   = len(results)
    errors  = sum(1 for r in results if "error" in r)
    good    = [r for r in results if "error" not in r]
    hot     = [r for r in good if (r.get("priority") or "").upper() == "HOT"]
    warm    = [r for r in good if (r.get("priority") or "").upper() == "WARM"]
    avg_score = (sum(r.get("lead_score", 0) for r in good) / len(good)) if good else 0
    total_savings = sum(r.get("annual_savings_yr1_usd", 0) for r in good)

    # Top 3 leads
    sorted_leads = sorted(good, key=lambda r: r.get("lead_score", 0), reverse=True)
    top3_lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, lead in enumerate(sorted_leads[:3]):
        grade   = lead.get("lead_grade", "D")
        addr    = lead.get("formatted_address") or lead.get("address", "?")
        score   = lead.get("lead_score", 0)
        savings = lead.get("annual_savings_yr1_usd", 0)
        top3_lines.append(f"{medals[i]} **[{grade}]** {addr}\n   Score: `{score}/100` | Savings: `${savings:,.0f}/yr`")

    top3_text = "\n\n".join(top3_lines) if top3_lines else "—"

    description = (
        f"Enriched **{total}** addresses from `{source_file}`\n"
        f"Errors: **{errors}** | Enriched: **{len(good)}**\n"
        f"Avg Score: **{avg_score:.1f}/100** | Pipeline: **${total_savings:,.0f}/yr**"
    )

    embed = {
        "title": f"☀️ Batch Enrichment Complete — {source_file}",
        "description": description,
        "color": COLOR_GREEN,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Solar Intelligence Suite · batch_enrich"},
        "fields": [
            {
                "name": "Lead Breakdown",
                "value": f"🔥 HOT: **{len(hot)}**\n☀️ WARM: **{len(warm)}**\n📋 Total: **{total}**",
                "inline": True,
            },
            {
                "name": "Top Prospects",
                "value": top3_text or "—",
                "inline": False,
            },
        ],
    }

    content = f"@here  🔥 **{len(hot)} HOT leads** found in batch!" if hot else "☀️ Batch enrichment complete."
    ok = _send({"content": content, "embeds": [embed]})

    # Also fire individual embeds for each HOT lead
    if not hot_only:
        for lead in hot[:5]:   # cap at 5 individual pings
            notify_hot_lead(lead, source=f"batch:{source_file}")
            time.sleep(0.5)    # rate-limit: 1 msg/0.5s

    return ok


# ── Territory scan ────────────────────────────────────────────────────────────

def notify_territory_scan(territory: dict) -> bool:
    """Send an embed summarizing a territory scan result."""
    if not territory:
        return False

    zip_code  = territory.get("zip_code", "?")
    city      = territory.get("city", "")
    state     = territory.get("state", "")
    grade     = territory.get("territory_grade", "?")
    hot       = territory.get("hot_leads", 0)
    warm      = territory.get("warm_leads", 0)
    total     = territory.get("leads_enriched", 0)
    avg_score = territory.get("avg_lead_score", 0)
    avg_save  = territory.get("avg_annual_savings", 0)
    sunshine  = territory.get("avg_sunshine_hours", 0)
    top_score = territory.get("top_lead_score", 0)

    loc_str = f"{city}, {state} {zip_code}".strip(", ")
    color   = _grade_color(grade)
    emoji   = _priority_emoji(grade if grade in ("HOT", "WARM", "COOL", "LOW") else
              ("HOT" if grade in ("A+", "A") else "WARM" if grade == "B" else "COOL"))

    embed = {
        "title": f"{emoji} Territory Scan — {loc_str}",
        "description": f"Grade: **{grade}** | Avg Score: `{_score_bar(avg_score)}`",
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Solar Intelligence Suite · territory scanner"},
        "fields": [
            {
                "name": "📊 Results",
                "value": (
                    f"Total Leads: **{total}**\n"
                    f"🔥 HOT: **{hot}**\n"
                    f"☀️ WARM: **{warm}**\n"
                    f"Top Score: **{top_score}/100**"
                ),
                "inline": True,
            },
            {
                "name": "💰 Economics",
                "value": (
                    f"Avg Savings: **${avg_save:,.0f}/yr**\n"
                    f"Avg Sunshine: **{sunshine:,.0f} hrs/yr**"
                ),
                "inline": True,
            },
        ],
    }

    content = f"🗺️ Territory scan complete: **{loc_str}**"
    if hot > 0:
        content = f"@here  🔥 **{hot} HOT leads** in {loc_str}!"

    return _send({"content": content, "embeds": [embed]})


# ── Daily digest ──────────────────────────────────────────────────────────────

def notify_daily_digest(digest_text: str = None, stats: dict = None) -> bool:
    """
    Post the daily digest to Discord.
    Can pass raw digest_text (posted as a code block) and/or stats dict for an embed.
    """
    sent = False

    if stats:
        total     = stats.get("total_leads", 0)
        hot       = stats.get("hot_leads", 0)
        warm      = stats.get("warm_leads", 0)
        avg_score = stats.get("avg_lead_score", 0.0)
        pipeline  = stats.get("total_pipeline_value", 0)
        avg_save  = stats.get("avg_annual_savings", 0.0)
        territories = stats.get("territory_count", 0)
        top_addr  = stats.get("top_lead_address", "")
        top_score = stats.get("top_lead_score", 0)

        # Territory leaderboard
        ranked = stats.get("territory_rankings", [])
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        rank_lines = []
        for i, t in enumerate(ranked[:5]):
            m   = medals[i] if i < len(medals) else "▫️"
            z   = t.get("zip_code", "?")
            c   = t.get("city", "")
            g   = t.get("territory_grade", "?")
            sc  = t.get("avg_lead_score", 0)
            h   = t.get("hot_leads", 0)
            rank_lines.append(f"{m} **{z}** {c} — [{g}] {sc:.0f}/100 | 🔥{h}")
        rank_text = "\n".join(rank_lines) if rank_lines else "—"

        embed = {
            "title": "☀️ Solar Intelligence Suite — Daily Digest",
            "description": (
                f"**{datetime.now(timezone.utc).strftime('%A, %B %d %Y')}**\n\n"
                f"Total Leads: **{total}**  |  HOT: **{hot}** 🔥  |  WARM: **{warm}** ☀️\n"
                f"Avg Score: **{avg_score:.1f}/100**  |  Pipeline: **${pipeline:,.0f}/yr**"
            ),
            "color": COLOR_GOLD,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Solar Intelligence Suite · daily_digest"},
            "fields": [
                {
                    "name": "📍 Territories Scanned",
                    "value": str(territories),
                    "inline": True,
                },
                {
                    "name": "💰 Avg Year-1 Savings",
                    "value": f"${avg_save:,.0f}",
                    "inline": True,
                },
                {
                    "name": "🏆 Top Prospect",
                    "value": f"{top_addr}\nScore: `{top_score}/100`" if top_addr else "—",
                    "inline": False,
                },
                {
                    "name": "🗺️ Territory Leaderboard",
                    "value": rank_text,
                    "inline": False,
                },
            ],
        }

        content = f"☀️ **Daily Digest** — {hot} HOT leads | ${pipeline:,.0f}/yr pipeline"
        sent = _send({"content": content, "embeds": [embed]})

    if digest_text:
        # Post as a long message (truncated to 1900 chars for Discord limit)
        chunk = digest_text[:1900]
        post_ok = _send({"content": f"```\n{chunk}\n```"})
        sent = sent or post_ok

    return sent


# ── Standalone test ───────────────────────────────────────────────────────────

def _run_test():
    """Send a test message + embed to verify the webhook is working."""
    url = WEBHOOK_URL or os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        print("❌ DISCORD_WEBHOOK_URL is not set. Export it and re-run.")
        print("   export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'")
        sys.exit(1)

    print(f"🔗 Webhook URL: {url[:60]}...")

    # Test 1: plain message
    ok = post_message("✅ Solar Intelligence Suite — Discord integration test")
    print(f"  Plain message: {'✅ sent' if ok else '❌ failed'}")

    # Test 2: fake HOT lead embed
    fake_lead = {
        "formatted_address": "1234 W Desert Blvd, Phoenix, AZ 85001",
        "lead_grade": "A+",
        "priority": "HOT",
        "lead_score": 88,
        "monthly_bill_usd": 195,
        "annual_savings_yr1_usd": 2380,
        "lifetime_savings_usd": 86200,
        "net_cost_usd": 18500,
        "payback_years": 7.8,
        "system_size_kw": 8.4,
        "panels_recommended": 21,
        "roof_segments": 6,
        "sunshine_hours_per_year": 2100,
        "imagery_date": "2024",
        "talking_points": [
            "✅ Your roof gets 2,100 hours of sunshine per year — excellent for Phoenix.",
            "💰 Based on your ~$195/month bill, you'd save roughly $2,380 in year one alone.",
        ],
        "score_breakdown": {
            "sunshine": 20,
            "roof_size": 15,
            "financial_fit": 18,
            "imagery_bonus": 4,
            "shading_penalty": 0,
        },
    }
    ok2 = notify_hot_lead(fake_lead, source="test")
    print(f"  HOT lead embed: {'✅ sent' if ok2 else '❌ failed'}")

    # Test 3: batch results summary
    ok3 = notify_batch_results([fake_lead], source_file="test_leads.csv", hot_only=True)
    print(f"  Batch summary embed: {'✅ sent' if ok3 else '❌ failed'}")

    # Test 4: daily digest
    fake_stats = {
        "total_leads": 12,
        "hot_leads": 8,
        "warm_leads": 3,
        "avg_lead_score": 83.5,
        "total_pipeline_value": 19200,
        "avg_annual_savings": 2150,
        "territory_count": 3,
        "top_lead_address": "1234 W Desert Blvd, Phoenix, AZ 85001",
        "top_lead_score": 88,
        "territory_rankings": [
            {"zip_code": "85234", "city": "Gilbert",  "territory_grade": "A+", "avg_lead_score": 85.5, "hot_leads": 5},
            {"zip_code": "85374", "city": "Surprise", "territory_grade": "A",  "avg_lead_score": 82.0, "hot_leads": 3},
            {"zip_code": "85326", "city": "Buckeye",  "territory_grade": "C",  "avg_lead_score": 0.0,  "hot_leads": 0},
        ],
    }
    ok4 = notify_daily_digest(stats=fake_stats)
    print(f"  Daily digest embed: {'✅ sent' if ok4 else '❌ failed'}")

    print("\nAll test messages sent! Check your Discord channel.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discord webhook integration for Solar Intelligence Suite")
    parser.add_argument("--test", action="store_true", help="Send test messages to verify webhook")
    parser.add_argument("--message", type=str, help="Send a custom message")
    args = parser.parse_args()

    if args.test:
        _run_test()
    elif args.message:
        ok = post_message(args.message)
        print("✅ Sent" if ok else "❌ Failed — check DISCORD_WEBHOOK_URL")
    else:
        parser.print_help()
