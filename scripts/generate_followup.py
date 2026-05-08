#!/usr/bin/env python3
"""
Solar Follow-Up Sequence Generator
===================================
Generates a personalized 5-touch SMS + email outreach sequence for any solar lead.
Each message is pre-filled with the prospect's real data: savings, payback, system size, etc.

Usage:
    python scripts/generate_followup.py "1905 E Marquette Dr, Gilbert AZ 85234" --bill 175
    python scripts/generate_followup.py "1905 E Marquette Dr, Gilbert AZ 85234" --bill 175 \
        --name "The Garcia Family" --rep "Jake Torres" --phone "602-555-0192"
    python scripts/generate_followup.py ... --json          # raw JSON output
    python scripts/generate_followup.py ... --txt           # save .txt to cache/followup/
    python scripts/generate_followup.py ... --no-color      # pipe-safe

API: POST /api/lead/followup
     GET  /api/lead/followup?address=...&monthly_bill=175
"""

import sys, os, json, argparse, textwrap
from datetime import datetime, timedelta
sys.path.insert(0, "/root/solar-tools")

# ── color helpers ─────────────────────────────────────────────────────────────

def c(text, code):
    return f"\033[{code}m{text}\033[0m"

BOLD = "1"; DIM = "2"; RED = "31"; GREEN = "32"; YELLOW = "33"
BLUE = "34"; MAGENTA = "35"; CYAN = "36"; WHITE = "37"
BG_DARK = "48;5;234"; BG_GREEN = "42"; BG_BLUE = "44"

PRIORITY_COLOR = {"HOT": RED, "WARM": YELLOW, "COOL": CYAN, "LOW": DIM}

# ── sequence templates ─────────────────────────────────────────────────────────

def _fmt_k(n):
    """Format number with K shorthand."""
    if n >= 1000:
        return f"${n/1000:.0f}K"
    return f"${n:.0f}"

def _fmt_usd(n):
    return f"${n:,.0f}"


def generate_sequence(lead: dict, homeowner_name: str = "", rep_name: str = "",
                      rep_phone: str = "", company_name: str = "Elevate Solar") -> dict:
    """
    Build a full 5-touch follow-up sequence from an enriched lead dict.
    Returns: {touches: [{day, channel, subject, body, notes}], summary: {}, lead: {}}
    """
    addr = lead.get("address", "your address")
    city = lead.get("city", "your area")
    score = lead.get("lead_score", 0)
    priority = lead.get("priority", "WARM")
    grade = lead.get("lead_grade", "B")
    savings_yr1 = lead.get("annual_savings_yr1_usd", 0)
    lifetime = lead.get("lifetime_savings_usd", 0)
    payback = lead.get("payback_years", 8)
    system_kw = lead.get("system_size_kw", 0)
    panels = lead.get("panels_recommended", 0)
    net_cost = lead.get("net_cost_usd", 0)
    gross_cost = lead.get("gross_cost_usd", 0)
    itc = lead.get("federal_itc_usd", 0)
    offset_pct = lead.get("offset_pct", 100)
    sunshine = lead.get("sunshine_hours_per_year", 2000)
    co2 = lead.get("co2_offset_lbs_per_year", 0)
    trees = lead.get("trees_equivalent_per_year", 0)
    monthly_bill = lead.get("monthly_bill_usd", 150)
    monthly_savings = round(savings_yr1 / 12)
    roi = lead.get("roi_25yr_pct", 0)

    name_first = homeowner_name.replace("The ", "").replace(" Family", "").strip()
    if not name_first:
        name_first = "Homeowner"
    greeting_sms = f"Hi {name_first}," if name_first != "Homeowner" else "Hi,"
    greeting_email = f"Hi {name_first}," if name_first != "Homeowner" else "Hello,"

    rep_sig_sms = f"\n— {rep_name} | {company_name}" if rep_name else f"\n— {company_name}"
    rep_sig_email_lines = []
    if rep_name:
        rep_sig_email_lines.append(f"Best,\n{rep_name}")
    else:
        rep_sig_email_lines.append(f"Best,\n{company_name} Team")
    if rep_phone:
        rep_sig_email_lines.append(f"📞 {rep_phone}")
    rep_sig_email_lines.append(f"🌞 {company_name}")
    rep_sig_email = "\n".join(rep_sig_email_lines)

    # Score-based urgency tier
    if priority == "HOT":
        urgency = "Your home is one of the top solar candidates in the area — homes like yours go fast in our scheduling queue."
        urgency_short = "Your home scored in the top tier for solar potential in {city}.".format(city=city)
    elif priority == "WARM":
        urgency = "Your home shows solid solar potential and qualifies for current incentive programs."
        urgency_short = "Your home qualifies for current federal solar incentives."
    else:
        urgency = "Solar incentives are available now — locking in sooner means more savings."
        urgency_short = "Federal solar incentives are available for your area now."

    itc_note = f"The 30% federal tax credit saves you {_fmt_usd(itc)} — bringing your out-of-pocket to just {_fmt_usd(net_cost)}."
    net_monthly = round((net_cost / (payback * 12))) if payback > 0 else 0

    # Day offsets for sequence
    today = datetime.now()
    def day_label(d):
        dt = today + timedelta(days=d)
        return dt.strftime("%A, %b %d")

    touches = [
        # ── Touch 1: Same day — SMS intro ─────────────────────────────────────
        {
            "touch": 1,
            "day": 0,
            "day_label": day_label(0),
            "channel": "SMS",
            "timing": "Same day — within 1 hour of door knock / inquiry",
            "subject": None,
            "body": (
                f"{greeting_sms} it was great chatting about solar today! "
                f"Quick summary for {addr.split(',')[0]}:\n\n"
                f"⚡ {panels} panels | {system_kw} kW system\n"
                f"💰 Save ~{_fmt_usd(monthly_savings)}/mo (${savings_yr1:,.0f}/yr)\n"
                f"🏛️ After 30% tax credit: {_fmt_usd(net_cost)}\n"
                f"📅 Payback: {payback} years | {_fmt_k(lifetime)} lifetime savings\n\n"
                f"Reply YES and I'll get your free quote locked in this week. "
                f"{urgency_short}"
                f"{rep_sig_sms}"
            ),
            "notes": "Send within 60 min of contact while interest is hot. Keep it short — data sells itself.",
            "cta": "Reply YES for free quote",
        },
        # ── Touch 2: Day 1 — Email deep dive ──────────────────────────────────
        {
            "touch": 2,
            "day": 1,
            "day_label": day_label(1),
            "channel": "Email",
            "timing": "Next day — morning send (9–10 AM)",
            "subject": f"Your solar numbers for {addr.split(',')[0]} — {_fmt_usd(savings_yr1)}/yr savings ☀️",
            "body": (
                f"{greeting_email}\n\n"
                f"As promised, here's a full breakdown for your home at {addr}.\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"☀️ YOUR SOLAR ANALYSIS — GRADE {grade}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📍 Address: {addr}\n"
                f"🔆 Annual sunshine: {sunshine:,.0f} hours/year\n"
                f"⚡ Recommended system: {panels} panels | {system_kw} kW\n"
                f"📊 Energy offset: {offset_pct}% of your usage\n\n"
                f"💵 FINANCIAL BREAKDOWN\n"
                f"  • Your current bill: {_fmt_usd(monthly_bill)}/mo\n"
                f"  • Estimated year-1 savings: {_fmt_usd(savings_yr1)}\n"
                f"  • Monthly savings: ~{_fmt_usd(monthly_savings)}/mo\n"
                f"  • Gross system cost: {_fmt_usd(gross_cost)}\n"
                f"  • 30% Federal Tax Credit: -{_fmt_usd(itc)}\n"
                f"  • NET cost to you: {_fmt_usd(net_cost)}\n"
                f"  • Simple payback: {payback} years\n"
                f"  • 25-year ROI: {roi:.0f}%\n"
                f"  • Lifetime savings: {_fmt_k(lifetime)}\n\n"
                f"🌱 ENVIRONMENTAL IMPACT\n"
                f"  • CO₂ offset: {co2:,.0f} lbs/year\n"
                f"  • Equivalent to planting {trees:.0f} trees/year\n\n"
                f"📋 NEXT STEPS\n"
                f"  1. Reply to this email or call/text me directly\n"
                f"  2. I'll schedule a free 20-min design consultation\n"
                f"  3. We'll finalize system specs + lock in your install date\n\n"
                f"⏰ Note: {urgency}\n\n"
                f"{rep_sig_email}"
            ),
            "notes": "Full data email. Attach or link to the HTML proposal if generated. Subject line A/B: try 'Your {city} home qualifies for $X,XXX in solar savings' as variant.",
            "cta": "Reply to schedule free consultation",
        },
        # ── Touch 3: Day 3 — SMS nudge ────────────────────────────────────────
        {
            "touch": 3,
            "day": 3,
            "day_label": day_label(3),
            "channel": "SMS",
            "timing": "Day 3 — midday (11 AM–1 PM)",
            "subject": None,
            "body": (
                f"{greeting_sms} just following up on your solar analysis for "
                f"{addr.split(',')[0]}. "
                f"Did you get a chance to look over the numbers?\n\n"
                f"Quick reminder: {itc_note}\n\n"
                f"Happy to answer any questions or jump on a quick call. "
                f"What day works best this week?"
                f"{rep_sig_sms}"
            ),
            "notes": "Short nudge — reference the ITC savings specifically. Don't re-send all the numbers. Ask a direct calendar question.",
            "cta": "Schedule a call",
        },
        # ── Touch 4: Day 7 — Email: financing angle ───────────────────────────
        {
            "touch": 4,
            "day": 7,
            "day_label": day_label(7),
            "channel": "Email",
            "timing": "Day 7 — morning send",
            "subject": f"Go solar for ~{_fmt_usd(net_monthly)}/mo — less than your current bill 💡",
            "body": (
                f"{greeting_email}\n\n"
                f"I wanted to share one more angle on your {addr.split(',')[0]} solar project "
                f"that most homeowners find really compelling:\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💳 SOLAR FINANCING — WHAT IT ACTUALLY COSTS\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Option 1: Cash purchase\n"
                f"  Net cost after tax credit: {_fmt_usd(net_cost)}\n"
                f"  Year-1 savings: {_fmt_usd(savings_yr1)} → payback in {payback} yrs\n\n"
                f"Option 2: Solar loan (most popular ⭐)\n"
                f"  Estimated monthly payment: ~{_fmt_usd(net_monthly)}/mo\n"
                f"  Your current bill: {_fmt_usd(monthly_bill)}/mo\n"
                f"  Day-1 savings: ~{_fmt_usd(monthly_savings)}/mo\n"
                f"  → Many homeowners pay LESS for solar than their utility bill.\n\n"
                f"Option 3: Lease / PPA\n"
                f"  $0 down, fixed monthly rate — instant savings, no ownership.\n\n"
                f"The {_fmt_usd(itc)} federal tax credit is only available for systems installed "
                f"while incentive programs are active.\n\n"
                f"Still interested? I can have a full proposal ready in under 24 hours.\n\n"
                f"{rep_sig_email}"
            ),
            "notes": "Financing angle converts fence-sitters who think solar is too expensive. Emphasize the $0/mo delta for loan option. Works especially well if monthly_savings > net_monthly.",
            "cta": "Reply 'QUOTE' for formal proposal",
        },
        # ── Touch 5: Day 14 — SMS: last follow-up ─────────────────────────────
        {
            "touch": 5,
            "day": 14,
            "day_label": day_label(14),
            "channel": "SMS",
            "timing": "Day 14 — last follow-up",
            "subject": None,
            "body": (
                f"{greeting_sms} last check-in on your solar analysis — "
                f"you're looking at {_fmt_usd(savings_yr1)}/yr in savings and "
                f"{_fmt_k(lifetime)} over 25 years for {addr.split(',')[0]}.\n\n"
                f"If the timing isn't right, no worries at all. "
                f"Just reply LATER and I'll circle back when it works better for you.\n\n"
                f"If you're still interested, just reply and I'll get you taken care of this week."
                f"{rep_sig_sms}"
            ),
            "notes": "Final soft close. Give them an easy exit ('reply LATER') — this lowers resistance and often gets a response either way. Keep on a nurture list if LATER.",
            "cta": "Reply LATER to stay in nurture | or call/text to move forward",
        },
    ]

    summary = {
        "address": addr,
        "homeowner_name": homeowner_name or "Homeowner",
        "rep_name": rep_name or f"{company_name} Team",
        "rep_phone": rep_phone,
        "company_name": company_name,
        "lead_score": score,
        "priority": priority,
        "grade": grade,
        "annual_savings_usd": savings_yr1,
        "monthly_savings_usd": monthly_savings,
        "lifetime_savings_usd": lifetime,
        "net_cost_usd": net_cost,
        "federal_itc_usd": itc,
        "payback_years": payback,
        "system_kw": system_kw,
        "panels": panels,
        "roi_25yr_pct": roi,
        "touch_count": len(touches),
        "channels": ["SMS", "Email", "SMS", "Email", "SMS"],
        "total_days": 14,
        "generated_at": datetime.now().isoformat(),
    }

    return {"touches": touches, "summary": summary, "lead": lead}


def print_sequence(seq: dict, use_color: bool = True):
    """Print the sequence to stdout with ANSI color."""
    def C(text, code):
        return c(text, code) if use_color else text

    summary = seq["summary"]
    lead = seq["lead"]
    touches = seq["touches"]
    priority = summary["priority"]
    pc = PRIORITY_COLOR.get(priority, WHITE)

    width = 72
    print()
    print(C("═" * width, CYAN))
    print(C("  ☀  SOLAR FOLLOW-UP SEQUENCE", f"{BOLD};{CYAN}") +
          C(f"  —  {summary['address'][:50]}", WHITE))
    print(C("═" * width, CYAN))
    print()

    # Lead snapshot
    grade_str = C(f" {summary['grade']} ", f"{BOLD};{BG_GREEN}" if priority == "HOT" else f"{BOLD};{BG_BLUE}")
    priority_str = C(f" {priority} ", f"{BOLD};{pc}")
    print(C("  LEAD SNAPSHOT", f"{BOLD};{WHITE}"))
    print(f"  Grade: {grade_str} {priority_str}  Score: {C(str(summary['lead_score']), BOLD)}/100")
    print(f"  💰 Yr1 Savings: {C(_fmt_usd(summary['annual_savings_usd']), GREEN)}  "
          f"Monthly: {C(_fmt_usd(summary['monthly_savings_usd']), GREEN)}/mo")
    print(f"  🔆 System: {summary['panels']} panels | {summary['system_kw']} kW | "
          f"Payback: {summary['payback_years']} yrs")
    print(f"  🏛️  Net Cost: {C(_fmt_usd(summary['net_cost_usd']), YELLOW)}  "
          f"(ITC saves {C(_fmt_usd(summary['federal_itc_usd']), GREEN)})")
    print(f"  📈 25-yr ROI: {C(str(summary['roi_25yr_pct']) + '%', GREEN)}  "
          f"Lifetime: {C(_fmt_k(summary['lifetime_savings_usd']), GREEN)}")
    print()

    rep_info = []
    if summary["rep_name"]:
        rep_info.append(f"Rep: {summary['rep_name']}")
    if summary["rep_phone"]:
        rep_info.append(f"📞 {summary['rep_phone']}")
    if summary["company_name"]:
        rep_info.append(summary["company_name"])
    if rep_info:
        print(f"  {' | '.join(rep_info)}")
        print()

    print(C("─" * width, DIM))
    print(C(f"  5-TOUCH SEQUENCE  |  14 days  |  SMS × 3, Email × 2", f"{BOLD};{WHITE}"))
    print(C("─" * width, DIM))
    print()

    channel_colors = {"SMS": BLUE, "Email": MAGENTA}

    for touch in touches:
        ch = touch["channel"]
        cc = channel_colors.get(ch, WHITE)
        day_lbl = f"Day {touch['day']}" if touch["day"] > 0 else "Day 0 (Today)"

        print(C(f"  ┌─ TOUCH {touch['touch']}  [{ch}]  —  {day_lbl}  ({touch['day_label']})", f"{BOLD};{cc}"))
        print(C(f"  │  Timing: {touch['timing']}", DIM))

        if touch.get("subject"):
            print(f"  │  {C('Subject:', BOLD)} {touch['subject']}")

        print(C(f"  │", DIM))
        # Wrap body text
        body_lines = touch["body"].split("\n")
        for line in body_lines:
            if len(line) > 65:
                wrapped = textwrap.wrap(line, width=65)
                for wl in wrapped:
                    print(f"  │  {wl}")
            else:
                print(f"  │  {line}")

        print(C(f"  │", DIM))
        print(f"  │  {C('📋 Notes:', BOLD)} {touch['notes']}")
        print(f"  │  {C('CTA:', BOLD)} {touch['cta']}")
        print(C(f"  └{'─' * 65}", f"{cc}"))
        print()

    print(C("═" * width, CYAN))
    print(C(f"  ✅ Sequence complete — {len(touches)} touches over {summary['total_days']} days", f"{BOLD};{GREEN}"))
    print(C(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", DIM))
    print(C("═" * width, CYAN))
    print()


def save_txt(seq: dict, output_path: str = None) -> str:
    """Save plain-text version of the sequence."""
    import re
    from pathlib import Path

    summary = seq["summary"]
    if not output_path:
        out_dir = Path("/root/solar-tools/cache/followup")
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r'[^a-z0-9]+', '_', summary['address'].lower())[:60]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(out_dir / f"followup_{slug}_{ts}.txt")

    lines = []
    lines.append("=" * 72)
    lines.append(f"SOLAR FOLLOW-UP SEQUENCE — {summary['address']}")
    lines.append(f"Generated: {summary['generated_at']}")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"Lead Grade: {summary['grade']} | Priority: {summary['priority']} | Score: {summary['lead_score']}/100")
    lines.append(f"Annual Savings: {_fmt_usd(summary['annual_savings_usd'])} | Monthly: {_fmt_usd(summary['monthly_savings_usd'])}/mo")
    lines.append(f"System: {summary['panels']} panels | {summary['system_kw']} kW | Payback: {summary['payback_years']} yrs")
    lines.append(f"Net Cost: {_fmt_usd(summary['net_cost_usd'])} (ITC: -{_fmt_usd(summary['federal_itc_usd'])})")
    lines.append(f"25-yr ROI: {summary['roi_25yr_pct']}% | Lifetime Savings: {_fmt_k(summary['lifetime_savings_usd'])}")
    lines.append("")
    if summary.get("rep_name"):
        lines.append(f"Rep: {summary['rep_name']} | {summary.get('rep_phone', '')} | {summary['company_name']}")
        lines.append("")

    lines.append("─" * 72)
    lines.append("5-TOUCH SEQUENCE  |  14 days  |  SMS × 3, Email × 2")
    lines.append("─" * 72)
    lines.append("")

    for touch in seq["touches"]:
        day_lbl = f"Day {touch['day']}" if touch["day"] > 0 else "Day 0 (Today)"
        lines.append(f"TOUCH {touch['touch']} — [{touch['channel']}] — {day_lbl} ({touch['day_label']})")
        lines.append(f"Timing: {touch['timing']}")
        if touch.get("subject"):
            lines.append(f"Subject: {touch['subject']}")
        lines.append("")
        # Strip ANSI just in case
        body = re.sub(r'\033\[[0-9;]*m', '', touch["body"])
        for line in body.split("\n"):
            lines.append(line)
        lines.append("")
        lines.append(f"Notes: {touch['notes']}")
        lines.append(f"CTA: {touch['cta']}")
        lines.append("─" * 72)
        lines.append("")

    lines.append("=" * 72)
    txt = "\n".join(lines)
    Path(output_path).write_text(txt, encoding="utf-8")
    return output_path


# ── CLI entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a 5-touch SMS + email follow-up sequence for a solar lead",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python scripts/generate_followup.py "1905 E Marquette Dr, Gilbert AZ"
              python scripts/generate_followup.py "1905 E Marquette Dr, Gilbert AZ" --bill 195 \\
                  --name "The Garcia Family" --rep "Jake Torres" --phone "602-555-0192"
              python scripts/generate_followup.py "1905 E Marquette Dr, Gilbert AZ" --json
              python scripts/generate_followup.py "1905 E Marquette Dr, Gilbert AZ" --txt
        """)
    )
    parser.add_argument("address", help="Full street address")
    parser.add_argument("--bill", type=float, default=175, help="Monthly electric bill (default: $175)")
    parser.add_argument("--rate", type=float, default=0.14, help="Utility rate $/kWh (default: 0.14)")
    parser.add_argument("--name", default="", help="Homeowner name (e.g. 'The Garcia Family')")
    parser.add_argument("--rep", default="", help="Rep name (e.g. 'Jake Torres')")
    parser.add_argument("--phone", default="", help="Rep phone number")
    parser.add_argument("--company", default="Elevate Solar", help="Company name")
    parser.add_argument("--json", action="store_true", dest="json_out", help="Output raw JSON")
    parser.add_argument("--txt", action="store_true", help="Save .txt to cache/followup/")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    parser.add_argument("--output", default="", help="Custom output path for --txt save")
    args = parser.parse_args()

    from core.solar import enrich_lead
    lead = enrich_lead(args.address, args.bill, args.rate)
    if "error" in lead:
        print(f"ERROR: {lead['error']}", file=sys.stderr)
        sys.exit(1)

    seq = generate_sequence(
        lead,
        homeowner_name=args.name,
        rep_name=args.rep,
        rep_phone=args.phone,
        company_name=args.company,
    )

    if args.json_out:
        print(json.dumps(seq, indent=2))
        return

    use_color = not args.no_color and sys.stdout.isatty()
    print_sequence(seq, use_color=use_color)

    if args.txt:
        path = save_txt(seq, args.output or None)
        msg = f"\n✅ Saved to: {path}"
        print(c(msg, GREEN) if use_color else msg)


if __name__ == "__main__":
    main()
