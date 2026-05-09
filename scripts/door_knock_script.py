#!/usr/bin/env python3
"""
Door-Knock Script Generator
Generates a personalized, data-driven door-knocking sales script for field reps.
Pulls real solar data from the API / local enrichment and weaves it into a
proven 5-step framework:
  1. OPENER        – name-drop neighborhood, build instant rapport
  2. DISCOVERY     – one soft qualifying question
  3. PIVOT         – transition from discovery to solar using their data
  4. PROOF POINTS  – 3 personalized bullets (savings, system size, payback)
  5. CLOSE         – low-pressure next-step CTA

CLI:
    python scripts/door_knock_script.py "1905 E Marquette Dr, Gilbert AZ" --bill 175
    python scripts/door_knock_script.py "address" --bill 195 --no-color
    python scripts/door_knock_script.py "address" --bill 175 --save /tmp/script.txt

API endpoint added to api.py:
    GET  /api/lead/door-script?address=...&monthly_bill=175
    POST /api/lead/door-script  body: {"address": "...", "monthly_bill": 175}
"""

import sys, os, json, argparse, textwrap
from datetime import datetime

sys.path.insert(0, "/root/solar-tools")

# ── ANSI colors ───────────────────────────────────────────────────────────────
GREEN   = "\033[92m";  YELLOW  = "\033[93m";  RED    = "\033[91m"
CYAN    = "\033[96m";  WHITE   = "\033[97m";  GRAY   = "\033[90m"
BOLD    = "\033[1m";   RESET   = "\033[0m";   BLUE   = "\033[94m"
MAGENTA = "\033[95m";  DIM     = "\033[2m"

def _c(text: str, *codes: str, use_color: bool = True) -> str:
    if not use_color:
        return text
    return "".join(codes) + text + RESET


# ── Core generator ────────────────────────────────────────────────────────────

def generate_door_knock_script(lead: dict | None, monthly_bill: float = 175.0) -> dict:
    """
    Build a full door-knock script dict from an enriched lead.
    If lead is None, returns a generic script using only the bill amount.
    """
    # Pull fields — gracefully fall back to generic values if missing
    address       = (lead or {}).get("address", "this neighborhood")
    city          = (lead or {}).get("city", "your area")
    state         = (lead or {}).get("state", "")
    sun_hrs       = (lead or {}).get("sunshine_hours_per_year", 0)
    system_kw     = (lead or {}).get("system_size_kw", 0)
    annual_savings= (lead or {}).get("annual_savings_yr1_usd", 0)
    lifetime_sav  = (lead or {}).get("lifetime_savings_usd", 0)
    payback       = (lead or {}).get("payback_years", 0)
    offset_pct    = (lead or {}).get("offset_pct", 0)
    net_cost      = (lead or {}).get("net_cost_usd", 0)
    federal_itc   = (lead or {}).get("federal_itc_usd", 0)
    score         = (lead or {}).get("lead_score", 0)
    grade         = (lead or {}).get("lead_grade", "?")
    priority      = (lead or {}).get("priority", "UNKNOWN")
    panels        = (lead or {}).get("panels_recommended", 0)
    co2_lbs       = (lead or {}).get("co2_offset_lbs_per_year", 0)
    trees         = (lead or {}).get("trees_equivalent_per_year", 0)
    roof_segs     = (lead or {}).get("roof_segments", 0)
    gross_cost    = (lead or {}).get("gross_cost_usd", 0)
    roi_25yr      = (lead or {}).get("roi_25yr_pct", 0)

    has_data = lead is not None and annual_savings > 0

    # Monthly savings
    monthly_savings = round(annual_savings / 12) if annual_savings else round(monthly_bill * 0.85)
    monthly_cost_waiting = round(monthly_bill * 0.035)  # 3.5% annual escalation → monthly
    yrs_to_payback = f"{payback:.1f}" if payback else "~8"

    # ── STEP 1: OPENER ────────────────────────────────────────────────────────
    city_display = city if city else "your neighborhood"
    state_display = f", {state}" if state else ""
    opener = (
        f"Hi there! My name is [YOUR NAME] — I'm working with a solar team helping homeowners "
        f"in {city_display}{state_display} cut their electric bills. "
        f"I was actually just finishing up a project a couple streets over and wanted to drop by while I was in the area."
    )
    if sun_hrs and sun_hrs > 1800:
        opener += (
            f" This part of {city_display} actually gets some of the best sun exposure in the region — "
            f"over {int(sun_hrs):,} hours a year — so a lot of neighbors are taking advantage of it."
        )

    # ── STEP 2: DISCOVERY QUESTION ────────────────────────────────────────────
    discovery = (
        f"Quick question — roughly what are you paying in electric right now? "
        f"Ballpark is fine."
    )
    discovery_followup = (
        f"[If they say ~${int(monthly_bill)}/mo] Perfect — that's actually exactly the range "
        f"where solar makes the most sense financially. Let me show you why."
    )
    if monthly_bill >= 200:
        discovery_note = "⚡ HIGH-BILL LEAD — emphasize immediate day-1 savings, monthly delta is big."
    elif monthly_bill >= 150:
        discovery_note = "💡 SOLID BILL — frame around locking in low rate before next utility hike."
    else:
        discovery_note = "📊 MODERATE BILL — lead with environmental + long-term savings angle."

    # ── STEP 3: PIVOT ─────────────────────────────────────────────────────────
    if has_data:
        pivot = (
            f"So we actually ran the numbers for homes in your specific area using satellite data — "
            f"your roof is facing the right direction, you have plenty of usable space, "
            f"and based on a ${int(monthly_bill)}/month bill, a system on this home "
            f"would produce about {int(offset_pct)}% of your annual electricity."
        )
    else:
        pivot = (
            f"So we ran the numbers for homes in this area — "
            f"based on a ${int(monthly_bill)}/month bill, a typical system here "
            f"could cover 90–100% of your annual electricity needs."
        )

    # ── STEP 4: PROOF POINTS ─────────────────────────────────────────────────
    proof_points = []
    if annual_savings:
        proof_points.append(
            f"💰 Year-one savings of ${int(annual_savings):,} — that's ${int(monthly_savings)}/month back in your pocket."
        )
    else:
        proof_points.append(
            f"💰 Estimated ${int(monthly_bill * 0.85):,}/year in savings — nearly eliminating your electric bill."
        )

    if payback:
        proof_points.append(
            f"📅 You break even in {yrs_to_payback} years, then enjoy free power for the remaining {25 - int(float(yrs_to_payback))}+ years of the system's life."
        )
    else:
        proof_points.append(
            f"📅 Most homeowners break even in 7–9 years, then enjoy free electricity for 15+ more years."
        )

    if federal_itc:
        proof_points.append(
            f"🏛️ The 30% federal tax credit takes your cost from ${int(gross_cost):,} down to just ${int(net_cost):,} — that's ${int(federal_itc):,} back at tax time."
        )
    else:
        proof_points.append(
            f"🏛️ The 30% federal tax credit immediately reduces your out-of-pocket by nearly a third."
        )

    if lifetime_sav:
        proof_points.append(
            f"📈 Over 25 years, total lifetime savings: ${int(lifetime_sav):,} — that's a {int(roi_25yr)}% return on investment."
        )

    if co2_lbs:
        proof_points.append(
            f"🌱 You'd offset {int(co2_lbs):,} lbs of CO₂ per year — the equivalent of planting {int(trees)} trees."
        )

    # Cost-of-waiting hook
    annual_utility_increase = round(monthly_bill * 12 * 0.035)
    proof_points.append(
        f"⏰ Utility rates go up ~3.5% every year — every month you wait costs roughly ${monthly_cost_waiting} more in future bills. "
        f"That's ${annual_utility_increase}/year you won't get back."
    )

    # ── STEP 5: CLOSE ────────────────────────────────────────────────────────
    close_options = [
        {
            "label": "Soft Close (recommended for cold door)",
            "script": (
                f"I'm not here to sell you anything today — I just wanted to make sure you had the numbers. "
                f"What I'd love to do is set up a quick 15-minute call with our energy specialist — "
                f"they'll build you a custom quote with no obligation. Would [day] or [day] work better for you?"
            )
        },
        {
            "label": "Direct Close (for warm / engaged homeowner)",
            "script": (
                f"I can get you a full custom proposal today — it takes about 10 minutes, completely free. "
                f"Mind if we sit down and I show you exactly what this looks like for your home?"
            )
        },
        {
            "label": "Referral Close (if they already have solar)",
            "script": (
                f"Oh that's great — glad it's working for you! "
                f"Do you have any neighbors on this street who might still be paying that high electric bill? "
                f"We do a referral bonus — ${250} for every qualified appointment you send our way."
            )
        }
    ]

    # ── OBJECTION INOCULATION ─────────────────────────────────────────────────
    objections = [
        {
            "objection": "\"I need to think about it.\"",
            "rebuttal": (
                f"Totally understand — what specifically would you want to think through? "
                f"Is it the cost, the process, or something else? "
                f"[Listen, address concern directly.] "
                f"The only thing I'd say is — every month is another ${int(monthly_cost_waiting)} more "
                f"on your utility bill that you could've been saving."
            )
        },
        {
            "objection": "\"I rent / I'm moving soon.\"",
            "rebuttal": (
                f"Completely fair — solar actually adds 4–6% to home value, "
                f"so if you're selling, it could net you an extra ${int(net_cost * 0.05):,}–${int(net_cost * 0.06):,} at closing. "
                f"Even renters can benefit through programs like community solar. Want me to leave some info?"
            )
        },
        {
            "objection": "\"We already looked into solar and it was too expensive.\"",
            "rebuttal": (
                f"Prices have dropped over 60% in the last 8 years — "
                f"what you were quoted before is likely very different today. "
                f"For a ${int(monthly_bill)}/month bill like yours, "
                f"a lot of homeowners are seeing $0-down with payments LOWER than their current bill. "
                f"Would it be worth a fresh look?"
            )
        },
        {
            "objection": "\"I don't want panels on my roof.\"",
            "rebuttal": (
                f"That's a common concern — modern panels are low-profile, "
                f"and we work with installers who are very careful about placement. "
                f"We could also look at ground-mount options if your lot allows. "
                f"What's the main concern — looks, structural, or something else?"
            )
        }
    ]

    # ── FIELD NOTES ──────────────────────────────────────────────────────────
    field_notes = []
    if has_data:
        field_notes.append(f"Lead Score: {score}/100 ({grade}) — Priority: {priority}")
        if roof_segs:
            field_notes.append(f"Roof: {roof_segs} segments, {panels} panels recommended → {system_kw} kW system")
        if sun_hrs:
            field_notes.append(f"Sun exposure: {int(sun_hrs):,} hrs/yr — {'★ Excellent' if sun_hrs >= 1900 else '✓ Good' if sun_hrs >= 1600 else '~ Average'}")
        imagery = (lead or {}).get("imagery_date", {})
        if imagery and imagery.get("year"):
            field_notes.append(f"Roof imagery: {imagery.get('month','?')}/{imagery.get('year','?')} ({'recent' if imagery.get('year',0) >= 2022 else 'dated — verify roof condition'})")
    if monthly_bill >= 200:
        field_notes.append("🔥 HIGH VALUE — escalate to senior rep if interested")
    if priority == "HOT":
        field_notes.append("🔥 HOT LEAD — close today if possible")

    return {
        "address":       address,
        "city":          city,
        "monthly_bill":  monthly_bill,
        "lead_score":    score,
        "lead_grade":    grade,
        "priority":      priority,
        "has_real_data": has_data,
        "script": {
            "step1_opener":        opener,
            "step2_discovery":     discovery,
            "step2_followup":      discovery_followup,
            "step2_rep_note":      discovery_note,
            "step3_pivot":         pivot,
            "step4_proof_points":  proof_points,
            "step5_close_options": close_options,
            "objection_handling":  objections,
            "field_notes":         field_notes,
        },
        "generated_at": datetime.now().isoformat(),
    }


# ── Pretty printer ────────────────────────────────────────────────────────────

def print_door_knock_script(result: dict, use_color: bool = True) -> str:
    C = lambda t, *c: _c(t, *c, use_color=use_color)
    lines = []
    W = 76

    def hr(char="═"):
        lines.append(C(char * W, CYAN, BOLD))

    def section(title: str, icon: str = ""):
        lines.append("")
        lines.append(C(f"  {icon}  {title}", YELLOW, BOLD) if icon else C(f"  {title}", YELLOW, BOLD))
        lines.append(C("  " + "─" * (W - 4), GRAY))

    def para(text: str, indent: int = 4, width: int = 68, color: str = WHITE):
        wrapped = textwrap.fill(text, width=width)
        for line in wrapped.splitlines():
            lines.append(C(" " * indent + line, color))

    hr("═")
    addr = result.get("address", "Unknown Address")
    score = result.get("lead_score", 0)
    grade = result.get("lead_grade", "?")
    priority = result.get("priority", "?")
    bill = result.get("monthly_bill", 0)
    has_data = result.get("has_real_data", False)

    lines.append(C(f"  🚪  DOOR-KNOCK SCRIPT GENERATOR", CYAN, BOLD))
    lines.append(C(f"  {'─'*(W-4)}", GRAY))
    lines.append(C(f"  📍 {addr}", WHITE))
    lines.append(C(f"  💵 Monthly Bill: ${int(bill)}", WHITE) +
                 (C(f"   |   Score: {score}/100 {grade}   |   Priority: {priority}",
                    GREEN if priority == "HOT" else YELLOW if priority == "WARM" else GRAY)
                  if has_data else ""))
    data_tag = C("  ✅ Real satellite data injected", GREEN) if has_data else C("  ℹ️  Generic script (no address enrichment)", GRAY)
    lines.append(data_tag)
    hr("═")

    s = result["script"]

    # STEP 1
    section("STEP 1 — OPENER (say within first 5 seconds)", "🗣️")
    para(s["step1_opener"], color=WHITE)

    # STEP 2
    section("STEP 2 — DISCOVERY QUESTION", "🔍")
    para(s["step2_discovery"], color=CYAN)
    lines.append("")
    para(s["step2_followup"], color=GRAY)
    lines.append("")
    lines.append(C(f"    💡 REP NOTE: {s['step2_rep_note']}", YELLOW))

    # STEP 3
    section("STEP 3 — THE PIVOT (transition to solar)", "🔄")
    para(s["step3_pivot"], color=WHITE)

    # STEP 4
    section("STEP 4 — PROOF POINTS (pick 3–4 that resonate)", "📊")
    for i, pt in enumerate(s["step4_proof_points"], 1):
        lines.append("")
        para(f"{i}. {pt}", color=GREEN if "$" in pt else WHITE)

    # STEP 5 - Close
    section("STEP 5 — CLOSE OPTIONS", "🤝")
    for opt in s["step5_close_options"]:
        lines.append("")
        lines.append(C(f"    ▶  {opt['label']}", MAGENTA, BOLD))
        para(opt["script"], color=WHITE)

    # Objections
    section("OBJECTION HANDLING (keep these in your back pocket)", "🛡️")
    for obj in s["objection_handling"]:
        lines.append("")
        lines.append(C(f"    ❓ {obj['objection']}", YELLOW, BOLD))
        para(obj["rebuttal"], color=WHITE)

    # Field Notes
    if s.get("field_notes"):
        section("FIELD NOTES (rep reference only, don't say aloud)", "📋")
        for note in s["field_notes"]:
            lines.append(C(f"    • {note}", GRAY))

    lines.append("")
    hr("═")
    gen = result.get("generated_at", "")[:16].replace("T", " ")
    lines.append(C(f"  Generated: {gen}  |  Solar Intelligence Suite", DIM))
    hr("═")
    lines.append("")

    output = "\n".join(lines)
    return output


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a personalized door-knock sales script from solar data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python scripts/door_knock_script.py "1905 E Marquette Dr, Gilbert AZ" --bill 175
              python scripts/door_knock_script.py "123 Main St, Phoenix AZ" --bill 225 --save /tmp/script.txt
              python scripts/door_knock_script.py --bill 175 --no-enrich
              python scripts/door_knock_script.py "address" --bill 175 --json
        """)
    )
    parser.add_argument("address", nargs="?", default=None, help="Street address to enrich")
    parser.add_argument("--bill",     type=float, default=175.0, help="Monthly electric bill in USD (default: 175)")
    parser.add_argument("--no-color", action="store_true",       help="Disable ANSI color output")
    parser.add_argument("--no-enrich",action="store_true",       help="Skip API enrichment, use generic script")
    parser.add_argument("--save",     type=str,   default=None,  help="Save script to file path")
    parser.add_argument("--json",     action="store_true",       help="Output raw JSON instead of formatted script")
    args = parser.parse_args()

    lead = None
    if args.address and not args.no_enrich:
        try:
            from core.solar import enrich_lead
            print(f"\033[90m  ⟳ Enriching {args.address} …\033[0m", file=sys.stderr)
            lead = enrich_lead(args.address, monthly_bill=args.bill)
        except Exception as e:
            print(f"\033[93m  ⚠ Enrichment failed ({e}) — using generic script\033[0m", file=sys.stderr)
            lead = None

    result = generate_door_knock_script(lead, monthly_bill=args.bill)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    output = print_door_knock_script(result, use_color=not args.no_color)
    print(output)

    if args.save:
        plain = print_door_knock_script(result, use_color=False)
        with open(args.save, "w") as f:
            f.write(plain)
        print(f"\033[90m  ✓ Script saved to {args.save}\033[0m")


if __name__ == "__main__":
    main()
