#!/usr/bin/env python3
"""
Appointment-Setting Communication Toolkit
Generates a full personalized outreach kit for solar sales reps:
  1. COLD CALL PHONE SCRIPT  — Word-for-word with real solar data
  2. VOICEMAIL DROP           — 15-second punchy message
  3. SMS SEQUENCE             — 3-touch text sequence (Day 1 / Day 3 / Day 7)
  4. EMAIL TEMPLATES          — Subject + body, warm intro + follow-up
  5. APPOINTMENT CONFIRMATION — Confirmation text + email

All templates inject real Google Solar API data (savings, score, payback, etc.)
when an address is supplied. Falls back to bill-based estimates if no address.

CLI:
    python scripts/appointment_setter.py "1905 E Marquette Dr, Gilbert AZ" --bill 175
    python scripts/appointment_setter.py --bill 200 --rep-name "Jake Rivera" --rep-phone "602-555-0100"
    python scripts/appointment_setter.py "address" --bill 175 --json
    python scripts/appointment_setter.py "address" --bill 175 --save /tmp/kit.txt --no-color

API:
    GET  /api/lead/appointment-setter?address=...&monthly_bill=175&rep_name=...
    POST /api/lead/appointment-setter  body: {address, monthly_bill, rep_name, rep_phone, rep_company}
"""

import sys, os, json, argparse, textwrap
from datetime import datetime

sys.path.insert(0, "/root/solar-tools")

# ── ANSI colors ────────────────────────────────────────────────────────────────
GREEN   = "\033[92m";  YELLOW  = "\033[93m";  RED     = "\033[91m"
CYAN    = "\033[96m";  WHITE   = "\033[97m";  GRAY    = "\033[90m"
BOLD    = "\033[1m";   RESET   = "\033[0m";   BLUE    = "\033[94m"
MAGENTA = "\033[95m";  DIM     = "\033[2m";   ITALIC  = "\033[3m"

def _c(text: str, *codes: str, use_color: bool = True) -> str:
    if not use_color:
        return text
    return "".join(codes) + text + RESET


# ── Core generator ─────────────────────────────────────────────────────────────

def generate_appointment_kit(
    lead: dict | None,
    monthly_bill: float = 175.0,
    rep_name: str = "[YOUR NAME]",
    rep_phone: str = "[YOUR PHONE]",
    rep_company: str = "our solar team",
) -> dict:
    """
    Build a complete appointment-setting comms kit from an enriched lead.
    Returns a dict with phone_script, voicemail, sms_sequence, email, confirm.
    """
    # ── Extract lead fields with graceful fallbacks ────────────────────────────
    has_data       = lead is not None and (lead.get("annual_savings_yr1_usd") or 0) > 0
    address        = (lead or {}).get("formatted_address") or (lead or {}).get("address") or "your home"
    city           = (lead or {}).get("city", "your area")
    state          = (lead or {}).get("state", "")
    score          = (lead or {}).get("lead_score", 0)
    grade          = (lead or {}).get("lead_grade", "")
    priority       = (lead or {}).get("priority", "")
    annual_savings = (lead or {}).get("annual_savings_yr1_usd") or 0
    lifetime_sav   = (lead or {}).get("lifetime_savings_usd") or 0
    payback        = (lead or {}).get("payback_years") or 0
    net_cost       = (lead or {}).get("net_cost_usd") or 0
    federal_itc    = (lead or {}).get("federal_itc_usd") or 0
    system_kw      = (lead or {}).get("system_size_kw") or 0
    sun_hrs        = (lead or {}).get("sunshine_hours_per_year") or 0
    panels         = (lead or {}).get("panels_recommended") or 0
    offset_pct     = (lead or {}).get("offset_pct") or 0

    # Derived values / safe estimates
    monthly_savings  = round(annual_savings / 12) if annual_savings else round(monthly_bill * 0.85)
    monthly_bill_int = int(monthly_bill)
    annual_savings_i = int(annual_savings) if annual_savings else int(monthly_bill * 0.85 * 12)
    lifetime_disp    = f"${int(lifetime_sav):,}" if lifetime_sav else f"${int(monthly_bill * 0.85 * 12 * 25):,}"
    payback_disp     = f"{payback:.1f}" if payback else "~7-9"
    net_cost_disp    = f"${int(net_cost):,}" if net_cost else "~$14,000-$17,000"
    itc_disp         = f"${int(federal_itc):,}" if federal_itc else "~$5,400-$7,200"
    system_kw_disp   = f"{system_kw:.1f} kW" if system_kw else "6-8 kW"
    city_disp        = city if city else "your area"
    location_disp    = f"{city_disp}, {state}" if state else city_disp
    annual_sav_disp  = f"${annual_savings_i:,}"
    monthly_sav_disp = f"${monthly_savings}"

    rep_name_first   = rep_name.split()[0] if rep_name and rep_name != "[YOUR NAME]" else "[YOUR NAME]"
    company_disp     = rep_company if rep_company != "our solar team" else "our team"

    # ── 1. COLD CALL PHONE SCRIPT ──────────────────────────────────────────────
    score_line = (
        f"Actually, I pulled the satellite data on your home — it scores {score}/100 for solar "
        f"potential. That puts you in the top tier for {city_disp}."
        if has_data else
        f"Actually, homes in {city_disp} typically score quite well for solar potential "
        f"based on roof orientation and sun exposure."
    )

    savings_line = (
        f"Based on your current bill of around ${monthly_bill_int}/month, our data shows "
        f"you could save roughly {annual_sav_disp} in year one — that's {monthly_sav_disp} "
        f"back in your pocket every single month."
        if has_data else
        f"For someone with a ${monthly_bill_int}/month bill like yours, the average homeowner "
        f"in {city_disp} saves {monthly_sav_disp} per month — about {annual_sav_disp} per year."
    )

    itc_line = (
        f"And right now with the 30% federal tax credit, the out-of-pocket is only "
        f"{net_cost_disp} — the ITC alone covers {itc_disp}."
        if has_data else
        f"And with the 30% federal tax credit, the out-of-pocket is typically "
        f"in the {net_cost_disp} range after incentives."
    )

    payback_line = (
        f"You'd break even in about {payback_disp} years, then it's essentially free energy "
        f"for the next 17+ years. Total lifetime savings: {lifetime_disp}."
        if has_data else
        f"Most homeowners break even in {payback_disp} years and then enjoy free energy "
        f"for the rest of the system's 25-year life."
    )

    phone_script = {
        "opener": (
            f"Hi, is this [HOMEOWNER NAME]? Hi {{}}, this is {rep_name_first} calling from "
            f"{company_disp}. How are you today? [Pause] Great!\n\n"
            f"The reason I'm calling — we've been doing solar consultations for homeowners "
            f"in {city_disp} and I wanted to reach out specifically about your home."
        ),
        "permission": (
            f"Do you have about 60 seconds? I ran an analysis on your property and I "
            f"found something I think you'd want to know about.\n\n"
            f"[IF YES → continue | IF NO → \"Totally understand — when would be a better time? "
            f"I can call back at literally any time.\"]"
        ),
        "data_hook": score_line,
        "savings_pitch": savings_line,
        "incentive": itc_line,
        "payback": payback_line,
        "soft_close": (
            f"I'd love to set up a quick 15-minute walkthrough — no pressure, no commitment. "
            f"I'll show you the exact numbers for your home and you decide if it makes sense. "
            f"Are you generally more available mornings or afternoons?"
        ),
        "objection_bridge_price": (
            f"I totally hear you on cost — that's why I want to show you the full picture. "
            f"The {itc_disp} federal credit changes everything. "
            f"Can I just email you a one-page summary?"
        ),
        "objection_bridge_thinking": (
            f"Absolutely, I wouldn't want you to rush. Here's what I'll do — "
            f"I'll text you the property report I pulled so you have the numbers in front of you. "
            f"What's the best number to send that to?"
        ),
        "close": (
            f"Perfect. I'll confirm [TIME/DATE] for a 15-minute walkthrough at your home. "
            f"You'll get a text confirmation from me in the next few minutes. "
            f"Does that cell number work for texts too? Great — see you then!"
        ),
    }

    # ── 2. VOICEMAIL DROP (≤20 seconds when read at normal pace) ──────────────
    vm_savings = annual_sav_disp if has_data else f"~${int(monthly_bill * 10):,}"
    voicemail = (
        f"Hi, this message is for [HOMEOWNER NAME] — it's {rep_name_first} with {company_disp}. "
        f"I ran a solar analysis on your home and the numbers look really strong — "
        f"we're talking {vm_savings} in potential year-one savings. "
        f"I'd love to show you the full report. Call me back at {rep_phone} — "
        f"that's {rep_phone}. Talk soon!"
    )

    # ── 3. SMS SEQUENCE ────────────────────────────────────────────────────────
    sms_day1_data = (
        f"I pulled the satellite data on your home — it scored {score}/100 for solar. "
        f"Year-one savings estimate: {annual_sav_disp}. "
        if has_data else
        f"Homes in {city_disp} with a ${monthly_bill_int}/mo bill typically save {monthly_sav_disp}/mo with solar. "
    )

    sms_sequence = [
        {
            "day": 1,
            "label": "Initial Outreach",
            "text": (
                f"Hi [NAME] — it's {rep_name_first} from {company_disp}. "
                + sms_day1_data +
                f"Free 15-min consult? Reply YES and I'll send the full report. – {rep_name_first} {rep_phone}"
            ),
        },
        {
            "day": 3,
            "label": "Follow-Up Nudge",
            "text": (
                f"Hey [NAME], {rep_name_first} again from {company_disp}. "
                f"Just wanted to make sure you got my message. "
                f"That {itc_disp} federal tax credit has a 2025 deadline — "
                f"I'd hate for you to miss it. Even a quick 10-minute call could save you thousands. "
                f"When's a good time? {rep_phone}"
            ),
        },
        {
            "day": 7,
            "label": "Final Touch (Soft Break-Up)",
            "text": (
                f"[NAME] — last message from me, I promise. "
                f"I still have the solar analysis for your home — "
                f"showing {annual_sav_disp}/yr savings and a {payback_disp}-year payback. "
                f"If the timing ever feels right, I'm here: {rep_phone}. "
                f"No pressure — just wanted to make sure you had the info. – {rep_name_first}"
            ),
        },
    ]

    # ── 4. EMAIL TEMPLATES ─────────────────────────────────────────────────────
    subject_line_1 = (
        f"Your home's solar report — {score}/100 ({city_disp})"
        if has_data else
        f"Quick question about your electric bill in {city_disp}"
    )
    body_data_section = (
        f"  • Solar Score:       {score}/100 ({grade} grade — {priority} priority)\n"
        f"  • Estimated Savings: {annual_sav_disp}/year | {monthly_sav_disp}/month\n"
        f"  • System Size:       {system_kw_disp} ({panels} panels)\n"
        f"  • Net Cost:          {net_cost_disp} after {itc_disp} federal tax credit\n"
        f"  • Payback Period:    {payback_disp} years\n"
        f"  • Lifetime Savings:  {lifetime_disp} over 25 years\n"
        if has_data else
        f"  • Your Bill:         ${monthly_bill_int}/month\n"
        f"  • Estimated Savings: {monthly_sav_disp}/month | {annual_sav_disp}/year\n"
        f"  • Federal Tax Credit: 30% of system cost (2025 deadline)\n"
        f"  • Typical Payback:   {payback_disp} years\n"
    )
    email_intro = {
        "subject": subject_line_1,
        "body": textwrap.dedent(f"""
Hi [FIRST NAME],

My name is {rep_name} with {company_disp}. I was doing solar assessments for homeowners
in {city_disp} and pulled a quick report on your property — I wanted to share what I found.

Here's what the data shows for your home:

{body_data_section}
Those numbers put your home in a strong position for solar. The 30% federal
investment tax credit ({itc_disp}) is the single biggest factor — it dramatically
reduces the real out-of-pocket cost.

I'd love to set up a free 15-minute walkthrough — no commitment, no pressure.
I'll show you the full system design and answer any questions you have.

Would [DAY] or [DAY] at [TIME] work for you? Or reply with what works
and I'll make it happen.

Best,
{rep_name}
{company_disp}
{rep_phone}

P.S. — Even if solar isn't right for you right now, the report might be useful.
Happy to send the PDF at no cost.
        """).strip(),
    }

    email_followup = {
        "subject": f"Re: Your solar report — did you get a chance to review?",
        "body": textwrap.dedent(f"""
Hi [FIRST NAME],

Just circling back on the solar report I shared for your home in {city_disp}.

I know life gets busy — totally understand. I wanted to make sure you had
the key numbers:

  → {annual_sav_disp} estimated first-year savings
  → {itc_disp} federal tax credit (30% of system cost)
  → {payback_disp}-year payback, then free energy for 17+ more years

If you have 10 minutes this week, I can walk you through everything on
a quick call. No slides, no pitch — just the numbers for YOUR home.

Would [DAY/TIME] work? Or reply and I'll work around your schedule.

{rep_name}
{rep_phone}
        """).strip(),
    }

    # ── 5. APPOINTMENT CONFIRMATION ────────────────────────────────────────────
    confirm_sms = (
        f"Hi [NAME]! Confirmed: [REP NAME] from {company_disp} will be there "
        f"[DATE] at [TIME]. We'll walk through your custom solar analysis — takes "
        f"about 15 min. Questions? {rep_phone}. See you then! ☀️"
    )

    confirm_email = {
        "subject": "Confirmed: Your Solar Consultation — [DATE] at [TIME]",
        "body": textwrap.dedent(f"""
Hi [FIRST NAME],

Your solar consultation is confirmed:

  📅 Date:     [DATE]
  🕐 Time:     [TIME]
  📍 Location: Your home / [ADDRESS]
  👤 Rep:      {rep_name} — {rep_phone}

What we'll cover in ~15 minutes:
  ✅ Your home's full solar analysis
  ✅ Exact system size + panel layout
  ✅ Net cost after the 30% federal tax credit
  ✅ Month-by-month savings projection
  ✅ Financing options (no money down available)

No commitment required — just information so you can make the best
decision for your home and family.

See you then!

{rep_name}
{company_disp}
{rep_phone}
        """).strip(),
    }

    return {
        "address": address if has_data else None,
        "score": score if has_data else None,
        "grade": grade if has_data else None,
        "priority": priority if has_data else None,
        "annual_savings_usd": annual_savings_i,
        "monthly_savings_usd": monthly_savings,
        "has_real_data": has_data,
        "rep_name": rep_name,
        "rep_phone": rep_phone,
        "rep_company": rep_company,
        "phone_script": phone_script,
        "voicemail": voicemail,
        "sms_sequence": sms_sequence,
        "email_intro": email_intro,
        "email_followup": email_followup,
        "confirm_sms": confirm_sms,
        "confirm_email": confirm_email,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


# ── Terminal renderer ──────────────────────────────────────────────────────────

def render_terminal(kit: dict, use_color: bool = True) -> str:
    def c(text, *codes):
        return _c(text, *codes, use_color=use_color)

    lines = []
    W = 72
    SEP = c("─" * W, GRAY)
    DSEP = c("═" * W, CYAN)

    # Header
    lines.append(DSEP)
    lines.append(c("  ☀  SOLAR APPOINTMENT-SETTER KIT", BOLD, YELLOW))
    if kit.get("has_real_data"):
        addr = kit.get("address", "")
        score = kit.get("score", 0)
        grade = kit.get("grade", "")
        prio  = kit.get("priority", "")
        color = GREEN if prio == "HOT" else (YELLOW if prio == "WARM" else GRAY)
        lines.append(c(f"  📍 {addr}  |  Score: {score}/100  |  Grade: {grade}  |  {prio}", color))
    else:
        lines.append(c("  ⚡ Generic mode — no address supplied", GRAY))

    ann = kit.get("annual_savings_usd", 0)
    mo  = kit.get("monthly_savings_usd", 0)
    lines.append(c(f"  💰 Est. Savings: ${ann:,}/year  |  ${mo}/month", WHITE))
    lines.append(c(f"  👤 Rep: {kit['rep_name']}  |  {kit['rep_phone']}", GRAY))
    lines.append(DSEP)
    lines.append("")

    def section(title, icon=""):
        lines.append(c(f"{icon} {title}", BOLD, CYAN))
        lines.append(SEP)

    def wrap_print(text, indent=4):
        for paragraph in text.split("\n\n"):
            wrapped = textwrap.fill(paragraph.strip(), width=W - indent,
                                    initial_indent=" " * indent,
                                    subsequent_indent=" " * indent)
            lines.append(wrapped)
            lines.append("")

    def field(label, text):
        lines.append(c(f"  [{label}]", BOLD, YELLOW))
        wrap_print(text)

    # 1. Phone Script
    section("COLD CALL PHONE SCRIPT", "📞")
    ps = kit["phone_script"]
    field("OPENER — Say this first", ps["opener"])
    field("PERMISSION — Ask if they have 60 sec", ps["permission"])
    field("DATA HOOK — Lead with their home's score", ps["data_hook"])
    field("SAVINGS PITCH — Paint the picture", ps["savings_pitch"])
    field("INCENTIVE — Federal tax credit anchor", ps["incentive"])
    field("PAYBACK — Long-term ROI", ps["payback"])
    field("SOFT CLOSE — Ask morning vs afternoon", ps["soft_close"])
    lines.append(c("  Objection bridges:", BOLD, MAGENTA))
    field("  → If 'too expensive'", ps["objection_bridge_price"])
    field("  → If 'need to think about it'", ps["objection_bridge_thinking"])
    field("CLOSE — Lock in the appointment", ps["close"])
    lines.append("")

    # 2. Voicemail
    section("VOICEMAIL DROP (≤20 sec)", "📲")
    lines.append(c("  Read this out loud — exactly as written:", ITALIC, GRAY))
    wrap_print(kit["voicemail"])

    # 3. SMS Sequence
    section("3-TOUCH SMS SEQUENCE", "💬")
    for sms in kit["sms_sequence"]:
        lines.append(c(f"  DAY {sms['day']} — {sms['label']}", BOLD, GREEN))
        lines.append(c(f"  {'─'*65}", GRAY))
        wrap_print(sms["text"])

    # 4. Email Templates
    section("EMAIL TEMPLATES", "📧")
    lines.append(c("  ── EMAIL 1: INTRO ──", BOLD, YELLOW))
    lines.append(c(f"  SUBJECT: {kit['email_intro']['subject']}", WHITE))
    lines.append(SEP)
    for line in kit["email_intro"]["body"].split("\n"):
        lines.append(f"    {line}")
    lines.append("")

    lines.append(c("  ── EMAIL 2: FOLLOW-UP ──", BOLD, YELLOW))
    lines.append(c(f"  SUBJECT: {kit['email_followup']['subject']}", WHITE))
    lines.append(SEP)
    for line in kit["email_followup"]["body"].split("\n"):
        lines.append(f"    {line}")
    lines.append("")

    # 5. Appointment Confirmation
    section("APPOINTMENT CONFIRMATION", "✅")
    lines.append(c("  CONFIRMATION TEXT:", BOLD, GREEN))
    wrap_print(kit["confirm_sms"])
    lines.append(c("  CONFIRMATION EMAIL:", BOLD, GREEN))
    lines.append(c(f"  SUBJECT: {kit['confirm_email']['subject']}", WHITE))
    lines.append(SEP)
    for line in kit["confirm_email"]["body"].split("\n"):
        lines.append(f"    {line}")
    lines.append("")

    lines.append(DSEP)
    lines.append(c("  ☀  Kit generated at " + kit["generated_at"], GRAY))
    lines.append(DSEP)

    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Solar Appointment-Setting Communication Toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python scripts/appointment_setter.py "1905 E Marquette Dr, Gilbert AZ" --bill 175
  python scripts/appointment_setter.py --bill 200 --rep-name "Jake Rivera" --rep-phone "602-555-0100"
  python scripts/appointment_setter.py "address" --bill 195 --json
  python scripts/appointment_setter.py "address" --bill 175 --no-color --save /tmp/kit.txt
        """,
    )
    parser.add_argument("address", nargs="?", default=None, help="Property address to analyze")
    parser.add_argument("--bill", type=float, default=175.0, help="Monthly electric bill (default: $175)")
    parser.add_argument("--rate", type=float, default=0.14, help="Utility rate per kWh (default: $0.14)")
    parser.add_argument("--rep-name", default="[YOUR NAME]", help="Sales rep full name")
    parser.add_argument("--rep-phone", default="[YOUR PHONE]", help="Sales rep phone number")
    parser.add_argument("--rep-company", default="our solar team", help="Company name")
    parser.add_argument("--no-enrich", action="store_true", help="Skip API call — use bill-only estimates")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--no-color", action="store_true", help="Plain text (pipe-safe)")
    parser.add_argument("--save", default=None, help="Save plain-text kit to a file")
    args = parser.parse_args()

    lead = None
    if args.address and not args.no_enrich:
        try:
            from core.solar import enrich_lead
            print(f"\033[90mEnriching {args.address}...\033[0m", file=sys.stderr)
            lead = enrich_lead(args.address, args.bill, args.rate)
            if lead.get("error"):
                print(f"\033[93mWarning: {lead['error']} — using estimate mode\033[0m", file=sys.stderr)
                lead = None
        except Exception as e:
            print(f"\033[93mWarning: enrichment failed ({e}) — using estimate mode\033[0m", file=sys.stderr)

    kit = generate_appointment_kit(
        lead=lead,
        monthly_bill=args.bill,
        rep_name=args.rep_name,
        rep_phone=args.rep_phone,
        rep_company=args.rep_company,
    )

    if args.json:
        print(json.dumps(kit, indent=2, default=str))
        return

    rendered = render_terminal(kit, use_color=not args.no_color)
    print(rendered)

    if args.save:
        plain = render_terminal(kit, use_color=False)
        with open(args.save, "w") as f:
            f.write(plain)
        print(f"\n\033[90mKit saved to {args.save}\033[0m", file=sys.stderr)


if __name__ == "__main__":
    main()
