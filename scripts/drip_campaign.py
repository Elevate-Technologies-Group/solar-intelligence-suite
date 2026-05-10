#!/usr/bin/env python3
"""
90-Day Lead Nurture Drip Campaign Generator
Builds a complete stage-aware email + SMS sequence for any pipeline lead.
Personalized with real Google Solar API satellite data.

Stages: new → contacted → qualified → proposed
Each stage gets a different campaign optimized for that buyer mindset.

CLI:
    python scripts/drip_campaign.py --lead-id 1                        # from pipeline DB
    python scripts/drip_campaign.py --address "1905 E Marquette Dr, Gilbert AZ" --bill 175
    python scripts/drip_campaign.py --lead-id 1 --format csv           # GHL import
    python scripts/drip_campaign.py --lead-id 1 --format json
    python scripts/drip_campaign.py --stage proposed --address "..." --bill 175

Importable:
    from scripts.drip_campaign import generate_drip_campaign
    campaign = generate_drip_campaign(lead, stage="contacted", monthly_bill=175)
"""

import sys, os, json, argparse, csv, io
from datetime import datetime, timedelta
sys.path.insert(0, "/root/solar-tools")

# ── ANSI colors ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"; YELLOW = "\033[93m"; RED    = "\033[91m"
CYAN   = "\033[96m"; WHITE  = "\033[97m"; GRAY   = "\033[90m"
BOLD   = "\033[1m";  RESET  = "\033[0m";  BLUE   = "\033[94m"
MAGENTA= "\033[95m"; DIM    = "\033[2m"

# ── Stage sequence definitions ────────────────────────────────────────────────
STAGE_INTRO = {
    "new": "🆕 NEW LEAD — First-Touch Nurture (0–30 days)",
    "contacted": "📞 CONTACTED — Post-Conversation Follow-Up (0–30 days)",
    "qualified": "✅ QUALIFIED — Pre-Proposal Warm-Up (0–30 days)",
    "proposed": "📄 PROPOSED — Proposal Follow-Up / Decision Sequence (0–21 days)",
}

# ─────────────────────────────────────────────────────────────────────────────
# CAMPAIGN TEMPLATES — {variable} placeholders filled at render time
# Each step: day (int), channel (sms|email), subject?, body, goal label
# ─────────────────────────────────────────────────────────────────────────────

CAMPAIGNS = {

    # ── NEW lead: never spoken, came in from widget/canvass/batch ────────────
    "new": [
        {
            "day": 0, "channel": "sms",
            "goal": "Instant response — strike while warm",
            "body": (
                "Hi {first_name}, I'm {rep_name} with {company}. "
                "I just ran a solar analysis on your home and it scored {score}/100 — {grade}. "
                "Your roof could save you around {savings_yr1} this year alone. "
                "When's a good time for a quick 10-minute call? 🌞"
            ),
        },
        {
            "day": 1, "channel": "email",
            "goal": "Intro + data hook",
            "subject": "Your home's solar score is in — {score}/100, {grade} 🌞",
            "body": (
                "Hi {first_name},\n\n"
                "My name is {rep_name} with {company}. I ran a free satellite solar analysis "
                "on your home and wanted to share the results directly.\n\n"
                "📊 YOUR HOME'S SOLAR SNAPSHOT\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  Address:        {address}\n"
                "  Solar Score:    {score}/100 — {grade} ★\n"
                "  Priority:       {priority}\n"
                "  Est. System:    {system_kw} kW ({panels} panels)\n"
                "  Year-1 Savings: {savings_yr1}\n"
                "  25-Year ROI:    {savings_25yr}\n"
                "  Federal ITC:    {itc_amount} back this tax season\n"
                "  Payback Period: {payback} years\n"
                "  Daily Sun Hrs:  {sun_hours} hrs/day\n\n"
                "Homeowners on your street are locking in these savings before the next rate hike. "
                "With {payback}-year payback and {savings_25yr} over the life of the system, "
                "solar is one of the strongest home investments available right now.\n\n"
                "Would you be open to a free 15-minute consultation? I can walk you through "
                "your custom proposal — no pressure, no commitment.\n\n"
                "Reply to this email or call/text me: {rep_phone}\n\n"
                "Best,\n{rep_name}\n{company}"
            ),
        },
        {
            "day": 3, "channel": "sms",
            "goal": "Soft nudge — keep top of mind",
            "body": (
                "Hey {first_name} — {rep_name} from {company}. "
                "Just wanted to make sure my solar analysis reached you. "
                "Your home scored {score}/100 — that's {grade} tier. "
                "Happy to answer any questions. What does your schedule look like this week?"
            ),
        },
        {
            "day": 5, "channel": "email",
            "goal": "Federal incentive urgency",
            "subject": "The {itc_amount} federal tax credit: what you need to know",
            "body": (
                "Hi {first_name},\n\n"
                "I wanted to flag something time-sensitive about your solar opportunity.\n\n"
                "💰 FEDERAL SOLAR TAX CREDIT (ITC)\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Homeowners who go solar this year qualify for a 30% federal tax credit. "
                "For a system sized for your home, that's approximately {itc_amount} back "
                "on your federal taxes — dollar-for-dollar, not just a deduction.\n\n"
                "On top of that, Arizona offers additional state incentives including:\n"
                "  • AZ Residential Solar Tax Credit (25%, up to $1,000)\n"
                "  • Property tax exemption on the added home value\n"
                "  • Sales tax exemption on solar equipment\n\n"
                "These incentives are scheduled to step down in future years. "
                "Homeowners who install now lock in the full 30% ITC.\n\n"
                "Your estimated net system cost after incentives: {net_cost}\n"
                "Monthly payment (vs your current {monthly_bill}/mo bill): see below 👇\n\n"
                "Many of our customers go solar for $0 down with monthly payments lower "
                "than their current electric bill — day-1 positive cash flow.\n\n"
                "Want me to run your financing options? Reply here or text me: {rep_phone}\n\n"
                "{rep_name}\n{company}"
            ),
        },
        {
            "day": 7, "channel": "sms",
            "goal": "Social proof + urgency",
            "body": (
                "Quick update {first_name} — a neighbor near you just went solar and "
                "locked in {savings_yr1}/year in savings. Your home scored even higher ({score}/100). "
                "The {itc_amount} tax credit window is open now. Worth a quick chat? — {rep_name}"
            ),
        },
        {
            "day": 10, "channel": "email",
            "goal": "Cost of waiting — rate escalation math",
            "subject": "What waiting 1 year costs you in Gilbert: {monthly_bill}/mo → the math",
            "body": (
                "Hi {first_name},\n\n"
                "I want to share a quick calculation that might change how you're thinking about timing.\n\n"
                "⏰ THE COST OF WAITING\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Your current monthly bill: {monthly_bill}\n"
                "Arizona utility rates have increased ~6% per year on average.\n\n"
                "If you wait 1 year:  You spend {waiting_1yr_cost} in bills + miss {savings_yr1} in savings\n"
                "If you wait 3 years: That's {waiting_3yr_cost} extra you'll never get back\n"
                "If you go solar now: Lock in {savings_yr1}/yr savings, {itc_amount} ITC, {payback} payback\n\n"
                "Every month you wait, your electric bill pays your utility company — not your future self.\n\n"
                "I'd love to show you a personalized 25-year savings projection for {address}. "
                "It takes 15 minutes and there's zero obligation. Can we set something up?\n\n"
                "{rep_name} | {rep_phone}\n{company}"
            ),
        },
        {
            "day": 14, "channel": "sms",
            "goal": "Light close attempt",
            "body": (
                "{first_name}, I've been holding a spot open in my install schedule for your area. "
                "Homes with your score ({score}/100) typically get approved fast. "
                "Do you want me to put together your custom proposal? Takes 5 min on a call. — {rep_name}"
            ),
        },
        {
            "day": 21, "channel": "email",
            "goal": "Check-in + value reinforcement",
            "subject": "Still thinking about solar? Here's your {savings_25yr} opportunity",
            "body": (
                "Hi {first_name},\n\n"
                "I know life gets busy, so I wanted to check in — not to pressure you, "
                "but because the numbers on your home are genuinely strong.\n\n"
                "Your satellite solar score: {score}/100 ({grade})\n"
                "Est. 25-year lifetime savings: {savings_25yr}\n"
                "Federal ITC still available: {itc_amount}\n"
                "System sized for your home: {system_kw} kW, {panels} panels\n\n"
                "If you have any questions — about the process, financing, the technology, "
                "anything at all — I'm happy to answer them with zero sales pressure.\n\n"
                "Just reply here or text me: {rep_phone}\n\n"
                "Looking forward to hearing from you,\n"
                "{rep_name}\n{company}"
            ),
        },
        {
            "day": 30, "channel": "sms",
            "goal": "Soft break-up / re-engagement",
            "body": (
                "Hey {first_name} — I don't want to bother you if solar just isn't the right fit right now. "
                "But your home's satellite score ({score}/100) puts you in the top tier for savings. "
                "If timing ever works, I'm here. — {rep_name}, {rep_phone}"
            ),
        },
    ],

    # ── CONTACTED: had a conversation, didn't set an appointment ────────────
    "contacted": [
        {
            "day": 0, "channel": "sms",
            "goal": "Recap + appreciation",
            "body": (
                "Hey {first_name}, great talking with you! "
                "As promised, I'm sending over your home's satellite data: "
                "Score {score}/100, {grade}, est. {savings_yr1}/yr savings, {itc_amount} ITC. "
                "I'll shoot you a full email summary now. — {rep_name}"
            ),
        },
        {
            "day": 1, "channel": "email",
            "goal": "Full data email + proposal preview",
            "subject": "Your solar summary from our call — {score}/100 {grade} | {savings_yr1}/yr",
            "body": (
                "Hi {first_name},\n\n"
                "Thanks for taking the time to chat today. Here's everything I promised — "
                "your complete satellite solar summary for {address}.\n\n"
                "📊 YOUR PERSONALIZED SOLAR ANALYSIS\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  Solar Score:       {score}/100 — {grade}\n"
                "  System Size:       {system_kw} kW ({panels} panels)\n"
                "  Year-1 Savings:    {savings_yr1}\n"
                "  25-Year Savings:   {savings_25yr}\n"
                "  Federal ITC (30%): {itc_amount}\n"
                "  Net System Cost:   {net_cost}\n"
                "  Payback Period:    {payback} years\n"
                "  Daily Sunlight:    {sun_hours} hrs/day\n"
                "  Energy Offset:     {offset_pct}%\n\n"
                "Based on what we discussed, here's what I'd suggest as your next step:\n"
                "  → Schedule a 30-min design consultation so I can build your custom proposal\n"
                "  → I'll show you exact panel placement, financing options, and month-by-month savings\n\n"
                "No commitment needed — just a closer look at your numbers.\n\n"
                "Reply here or call/text: {rep_phone}\n\n"
                "{rep_name}\n{company}"
            ),
        },
        {
            "day": 3, "channel": "sms",
            "goal": "Appointment ask",
            "body": (
                "{first_name}, did the email come through okay? "
                "I'd love to get your custom proposal built — it only takes about 30 minutes. "
                "Do you have time Thursday or Friday this week? — {rep_name}"
            ),
        },
        {
            "day": 5, "channel": "email",
            "goal": "ITC + financing options",
            "subject": "Your $0-down option: {savings_yr1}/yr savings with no upfront cost",
            "body": (
                "Hi {first_name},\n\n"
                "One thing I wanted to make sure I covered — your financing options.\n\n"
                "💳 COMMON PATHS FOR YOUR HOME\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  $0 Down Solar Loan:\n"
                "    • Monthly payment typically BELOW your current {monthly_bill} bill\n"
                "    • You keep the {itc_amount} federal tax credit\n"
                "    • Own your system outright — no lease complications\n\n"
                "  Cash Purchase:\n"
                "    • Full {itc_amount} tax credit + fastest payback ({payback} yrs)\n"
                "    • Best long-term ROI: {savings_25yr} over 25 years\n\n"
                "Many homeowners in {city} are surprised to find their solar payment "
                "is actually less than their current electric bill — day-1 positive cash flow.\n\n"
                "I can run your exact financing scenarios in our proposal call. "
                "Any questions before then?\n\n"
                "{rep_name} | {rep_phone}\n{company}"
            ),
        },
        {
            "day": 7, "channel": "sms",
            "goal": "Urgency — ITC window",
            "body": (
                "Hey {first_name} — just a heads-up, the 30% federal tax credit ({itc_amount}) "
                "is available NOW for installations this year. "
                "Getting your proposal built locks in your place in the schedule. "
                "Can we do a quick call this week? — {rep_name}"
            ),
        },
        {
            "day": 10, "channel": "email",
            "goal": "Thinking about it objection",
            "subject": "Still weighing it? Here's what {savings_yr1}/yr looks like over 10 years",
            "body": (
                "Hi {first_name},\n\n"
                "I completely understand taking time to think it over — "
                "it's a big decision and you want to get it right.\n\n"
                "Let me make it concrete with a 10-year picture:\n\n"
                "📆 10-YEAR COMPARISON\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "  WITHOUT solar (bills at 6% annual increase):\n"
                "    Year 1: {monthly_bill}/mo → Year 10: est. $"+"{monthly_bill_10yr}"+"/mo\n"
                "    Total spent on bills: {bills_10yr_total}\n\n"
                "  WITH solar on your home:\n"
                "    Year 1 savings: {savings_yr1}\n"
                "    10-year savings: {savings_10yr}\n"
                "    System paid off by: Year {payback}\n"
                "    After payback → {savings_yr1}/yr is pure profit 💚\n\n"
                "The question isn't whether you can afford solar — "
                "it's whether you can afford to keep paying the utility company.\n\n"
                "Happy to answer any specific concerns. What's holding you back?\n\n"
                "{rep_name} | {rep_phone}\n{company}"
            ),
        },
        {
            "day": 14, "channel": "sms",
            "goal": "Referral angle + social proof",
            "body": (
                "{first_name} — just helped a homeowner near {city} lock in "
                "{savings_yr1}/yr in savings. Their home scored similar to yours. "
                "If you know anyone who's been curious about solar, I can analyze their home too. "
                "And if you go solar through me, I'll take care of you both. — {rep_name}"
            ),
        },
        {
            "day": 21, "channel": "email",
            "goal": "Final value summary + soft close",
            "subject": "Last note on your solar opportunity — {score}/100 | {savings_25yr} over 25 yrs",
            "body": (
                "Hi {first_name},\n\n"
                "I don't want to keep cluttering your inbox, so I'll make this my last reach-out "
                "unless I hear from you.\n\n"
                "Your home's solar potential in summary:\n"
                "  ⭐ Score: {score}/100 — {grade}\n"
                "  💰 Year-1 savings: {savings_yr1}\n"
                "  🏦 Federal ITC: {itc_amount}\n"
                "  📅 Payback: {payback} years\n"
                "  🌿 25-year ROI: {savings_25yr}\n\n"
                "If solar ever makes sense for you down the road, I'll be here. "
                "And if you know neighbors or family who might benefit, I'm always happy to run a free analysis.\n\n"
                "It's been a pleasure, {first_name}.\n\n"
                "{rep_name}\n{rep_phone}\n{company}"
            ),
        },
    ],

    # ── QUALIFIED: passed qualification, building proposal ───────────────────
    "qualified": [
        {
            "day": 0, "channel": "sms",
            "goal": "Excitement + expectations",
            "body": (
                "Great news {first_name}! Your home at {address} qualified for solar. "
                "I'm building your custom proposal now — {system_kw} kW system, {savings_yr1}/yr est. savings. "
                "I'll have it ready in 48 hours. — {rep_name}"
            ),
        },
        {
            "day": 1, "channel": "email",
            "goal": "What to expect — process overview",
            "subject": "Your solar proposal is being built — here's what happens next",
            "body": (
                "Hi {first_name},\n\n"
                "Exciting news — your home has been qualified and I'm preparing your "
                "personalized solar proposal.\n\n"
                "🗓️ WHAT HAPPENS NEXT\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                "  1. Proposal built (next 48 hrs)\n"
                "     Your exact system: {system_kw} kW, {panels} panels\n"
                "     Optimized for your {sun_hours} hrs/day of Phoenix sun\n\n"
                "  2. Proposal review call (~30 min)\n"
                "     Walk through your custom savings, financing, and install timeline\n\n"
                "  3. Agreement & HOA approval (if needed)\n"
                "     We handle the paperwork — typical 1–2 week process\n\n"
                "  4. Installation (typically 1 day)\n"
                "     ROC-licensed installers, permits pulled for you\n\n"
                "  5. Utility interconnection + PTO\n"
                "     You flip the switch — the savings begin\n\n"
                "Your numbers so far:\n"
                "  Solar Score:    {score}/100 — {grade}\n"
                "  System Size:    {system_kw} kW\n"
                "  Year-1 Savings: {savings_yr1}\n"
                "  Federal ITC:    {itc_amount}\n\n"
                "Any questions before we meet? Reply here or text me: {rep_phone}\n\n"
                "{rep_name}\n{company}"
            ),
        },
        {
            "day": 3, "channel": "sms",
            "goal": "System size teaser",
            "body": (
                "Hey {first_name} — your proposal is looking really strong. "
                "A {system_kw} kW system fits your roof perfectly and should offset about {offset_pct}% "
                "of your current usage. More details in our call. When works best for you? — {rep_name}"
            ),
        },
        {
            "day": 5, "channel": "email",
            "goal": "Full personalized savings breakdown",
            "subject": "Your {system_kw} kW solar savings preview — {savings_yr1}/yr",
            "body": (
                "Hi {first_name},\n\n"
                "Here's a preview of your custom solar proposal data for {address}:\n\n"
                "⚡ YOUR CUSTOM SYSTEM SNAPSHOT\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  System Size:          {system_kw} kW\n"
                "  Panels:               {panels} high-efficiency panels\n"
                "  Avg Daily Sun:        {sun_hours} hours\n"
                "  Energy Offset:        {offset_pct}%\n"
                "  Est. Annual Output:   {annual_output_kwh} kWh\n\n"
                "💰 YOUR FINANCIAL PICTURE\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  Gross System Cost:    {gross_cost}\n"
                "  Federal ITC (30%):   −{itc_amount}\n"
                "  AZ State Credit:      −$1,000\n"
                "  Net Cost to You:      {net_cost}\n"
                "  Year-1 Savings:       {savings_yr1}\n"
                "  Payback Period:       {payback} years\n"
                "  25-Year Savings:      {savings_25yr}\n\n"
                "I'll have your full proposal ready for our call. "
                "Reply to confirm your appointment time.\n\n"
                "{rep_name} | {rep_phone}\n{company}"
            ),
        },
        {
            "day": 7, "channel": "sms",
            "goal": "ITC reminder",
            "body": (
                "{first_name} — reminder: the 30% ITC ({itc_amount}) applies to "
                "installations completed this year. Let's lock in your spot. "
                "Can we connect tomorrow or the day after? — {rep_name}"
            ),
        },
        {
            "day": 10, "channel": "email",
            "goal": "Neighborhood social proof",
            "subject": "Homeowners in {city} who made the switch — what they said",
            "body": (
                "Hi {first_name},\n\n"
                "Ahead of our proposal review, I wanted to share some feedback from "
                "homeowners in {city} who've made the switch.\n\n"
                "\"Our bill went from $240 to basically zero. I wish we'd done it sooner.\"\n"
                "— Homeowner, {city} area (score: 85/100)\n\n"
                "\"The install took one day. The ROI calculation was the easy part — "
                "the federal credit covered almost a third of it.\"\n"
                "— Homeowner, Phoenix metro (score: 79/100)\n\n"
                "Your home scored {score}/100 — that's in the top tier for our area. "
                "Your results should be even better.\n\n"
                "Looking forward to walking you through your custom proposal!\n\n"
                "{rep_name} | {rep_phone}\n{company}"
            ),
        },
        {
            "day": 14, "channel": "sms",
            "goal": "Proposal call scheduling",
            "body": (
                "Hey {first_name} — your proposal is ready! "
                "I'd love to walk you through your {system_kw} kW system and {savings_yr1}/yr savings. "
                "Takes about 20 minutes. What day works this week? — {rep_name}"
            ),
        },
    ],

    # ── PROPOSED: proposal sent, waiting on decision ──────────────────────────
    "proposed": [
        {
            "day": 0, "channel": "sms",
            "goal": "Proposal delivery confirmation",
            "body": (
                "Hey {first_name}! Just sent your personalized solar proposal to {email}. "
                "Key numbers: {system_kw} kW system, {savings_yr1}/yr savings, {itc_amount} ITC. "
                "Let me know when you've had a chance to look it over! — {rep_name}"
            ),
        },
        {
            "day": 1, "channel": "email",
            "goal": "Proposal follow-up + key numbers recap",
            "subject": "Your solar proposal is waiting — {savings_yr1}/yr | {itc_amount} back",
            "body": (
                "Hi {first_name},\n\n"
                "I wanted to make sure your proposal came through okay and highlight "
                "the three numbers that matter most:\n\n"
                "  1️⃣  {savings_yr1} — your estimated year-1 savings\n"
                "  2️⃣  {itc_amount} — your federal tax credit (30% ITC, available now)\n"
                "  3️⃣  {payback} years — your payback period, then pure savings forever\n\n"
                "After payback, your {system_kw} kW system keeps generating {savings_yr1}/yr "
                "for the life of the 25-year production warranty — that's {savings_25yr} total.\n\n"
                "Do you have any questions about the proposal? I'm happy to jump on a call "
                "and walk through it section by section.\n\n"
                "Reply here or text: {rep_phone}\n\n"
                "{rep_name}\n{company}"
            ),
        },
        {
            "day": 3, "channel": "sms",
            "goal": "Question opener",
            "body": (
                "Hey {first_name} — any questions about your proposal? "
                "I want to make sure all your questions are answered before you decide. "
                "What are you thinking so far? — {rep_name}"
            ),
        },
        {
            "day": 5, "channel": "email",
            "goal": "ROI breakdown — make the math crystal clear",
            "subject": "The math on your solar investment — {payback} years to breakeven, then {savings_25yr}",
            "body": (
                "Hi {first_name},\n\n"
                "I want to make sure the ROI on your proposal is crystal clear.\n\n"
                "📊 YOUR 25-YEAR INVESTMENT PICTURE\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  Net System Cost (after ITC): {net_cost}\n"
                "  Annual Savings:              {savings_yr1}/yr\n"
                "  Payback Year:                Year {payback}\n"
                "  Years of free power after:   {free_years} years\n"
                "  Lifetime savings (25 yrs):   {savings_25yr}\n"
                "  Net profit over 25 years:    {net_profit_25yr}\n\n"
                "Compare that to:\n"
                "  Keeping your current bill at {monthly_bill}/mo\n"
                "  25-year cost (6% annual rate increase): {bills_25yr_total}\n\n"
                "The difference is significant. Solar isn't an expense — it's a financial asset.\n\n"
                "Ready to move forward? I can have your agreement ready to sign today.\n\n"
                "{rep_name} | {rep_phone}\n{company}"
            ),
        },
        {
            "day": 7, "channel": "sms",
            "goal": "ITC urgency — tax year deadline",
            "body": (
                "{first_name} — quick heads-up: the {itc_amount} federal tax credit "
                "requires installation to be completed this tax year. "
                "Install schedules are filling up. Want to lock in your spot? — {rep_name}"
            ),
        },
        {
            "day": 10, "channel": "email",
            "goal": "Objection pre-emption + decision support",
            "subject": "Common questions about your proposal — answered",
            "body": (
                "Hi {first_name},\n\n"
                "I've helped a lot of homeowners make this decision, and I find the same "
                "questions come up. Let me answer them for your specific situation.\n\n"
                "❓ \"What if I move?\"\n"
                "Solar adds 4-6% to your home's value and studies show solar homes sell "
                "faster. You can transfer the system or roll the value into your sale price.\n\n"
                "❓ \"What about my roof?\"\n"
                "Your satellite data shows {panels} panels fitting cleanly on your roof — "
                "our engineering team will confirm before any installation begins. "
                "We only install on roofs we're confident in.\n\n"
                "❓ \"What if the panels don't produce enough?\"\n"
                "Your {system_kw} kW system is sized to offset {offset_pct}% of your usage. "
                "It comes with a 25-year production guarantee — if it underperforms, we make it right.\n\n"
                "❓ \"Is the financing a good deal?\"\n"
                "At {payback}-year payback and {savings_25yr} lifetime ROI, the numbers "
                "speak for themselves. Most of our customers say it's the best financial "
                "decision they've made as a homeowner.\n\n"
                "What other questions can I answer for you, {first_name}?\n\n"
                "{rep_name} | {rep_phone}\n{company}"
            ),
        },
        {
            "day": 14, "channel": "sms",
            "goal": "Decision check-in",
            "body": (
                "Hey {first_name}, I want to respect your decision-making process. "
                "Has anything come up that I can help answer? "
                "Install slots for your area are going quickly. — {rep_name}"
            ),
        },
        {
            "day": 21, "channel": "email",
            "goal": "Final offer / last call",
            "subject": "Final note on your solar proposal — {score}/100 | {savings_25yr} opportunity",
            "body": (
                "Hi {first_name},\n\n"
                "I don't want to keep sending emails if this isn't the right time, "
                "so I'll make this my last follow-up unless you reach out.\n\n"
                "Your proposal is still on file and ready to go:\n"
                "  ⭐ Solar Score: {score}/100 — {grade}\n"
                "  💰 Year-1 Savings: {savings_yr1}\n"
                "  🏦 Federal ITC: {itc_amount} (available this tax year)\n"
                "  📅 Payback: {payback} years\n"
                "  🌿 25-Year ROI: {savings_25yr}\n\n"
                "Whenever you're ready — whether that's today or 6 months from now — "
                "just text or call me and we'll pick right back up.\n\n"
                "It's been a pleasure getting to know you, {first_name}.\n\n"
                "{rep_name}\n{rep_phone}\n{company}"
            ),
        },
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Context builder
# ─────────────────────────────────────────────────────────────────────────────

def build_context(lead: dict, monthly_bill: float = 175.0, rep_name: str = "Your Solar Rep",
                  rep_phone: str = "602-555-0100", company: str = "Elevate Solar",
                  contact_name: str = "", email: str = "") -> dict:
    """Build {variable} substitution context from a lead dict."""

    # Pull financials — handle multiple field name conventions
    savings_yr1_raw = (lead.get("annual_savings_yr1_usd")
                       or lead.get("annual_savings_usd")
                       or monthly_bill * 12 * 0.85)
    savings_25yr_raw = lead.get("lifetime_savings_usd", savings_yr1_raw * 18)
    payback_raw = lead.get("payback_years", 8.5)
    itc_raw = (lead.get("federal_itc_usd")
               or lead.get("itc_credit_usd")
               or lead.get("itc_amount_usd")
               or savings_yr1_raw * 1.5)
    gross_cost_raw = (lead.get("gross_cost_usd")
                      or lead.get("system_cost_usd")
                      or savings_yr1_raw * 10.6)
    net_cost_raw = lead.get("net_cost_usd", gross_cost_raw - itc_raw - 1000)
    system_kw_raw = lead.get("system_size_kw", monthly_bill * 0.065)
    panels_raw = (lead.get("panels_recommended")
                  or lead.get("panels_count")
                  or int(system_kw_raw / 0.4))
    # sunshine_hours_per_year → convert to per_day
    sun_hrs_yr = lead.get("sunshine_hours_per_year")
    sun_hours_raw = round(sun_hrs_yr / 365, 1) if sun_hrs_yr else lead.get("sunshine_hours_per_day", 5.6)
    offset_pct_raw = lead.get("offset_pct", lead.get("energy_offset_pct", 90))
    score_raw = lead.get("lead_score", lead.get("score", 75))
    grade_raw = lead.get("lead_grade", lead.get("grade", "A"))
    priority_raw = lead.get("priority", "WARM")
    addr_raw = lead.get("formatted_address", lead.get("address", "your home"))

    # City extraction
    parts = addr_raw.split(",")
    city_raw = parts[1].strip() if len(parts) > 1 else "your city"

    # Annual output estimate
    annual_kwh = int(system_kw_raw * sun_hours_raw * 365)

    # Cost of waiting calculations
    bill_mo = monthly_bill
    rate_increase = 0.06
    waiting_1yr = sum(bill_mo * ((1 + rate_increase) ** (m / 12)) for m in range(12))
    waiting_3yr = sum(bill_mo * ((1 + rate_increase) ** (m / 12)) for m in range(36))
    savings_10yr = savings_yr1_raw * 10 * 1.03  # 3% savings growth
    bills_10yr = sum(bill_mo * 12 * ((1 + rate_increase) ** y) for y in range(10))
    bills_25yr = sum(bill_mo * 12 * ((1 + rate_increase) ** y) for y in range(25))
    net_profit_25yr = savings_25yr_raw - net_cost_raw
    free_years = max(0, 25 - int(payback_raw))
    bill_10yr_mo = bill_mo * ((1 + rate_increase) ** 10)

    # First name
    first = (contact_name or "there").split()[0] if contact_name else "there"

    return {
        "first_name": first,
        "contact_name": contact_name or "Homeowner",
        "email": email or "your email",
        "rep_name": rep_name,
        "rep_phone": rep_phone,
        "company": company,
        "address": addr_raw,
        "city": city_raw,
        "score": score_raw,
        "grade": grade_raw,
        "priority": priority_raw,
        "system_kw": f"{system_kw_raw:.1f}",
        "panels": panels_raw,
        "sun_hours": f"{sun_hours_raw:.1f}",
        "offset_pct": int(offset_pct_raw),
        "annual_output_kwh": f"{annual_kwh:,}",
        "savings_yr1": f"${savings_yr1_raw:,.0f}",
        "savings_25yr": f"${savings_25yr_raw:,.0f}",
        "savings_10yr": f"${savings_10yr:,.0f}",
        "gross_cost": f"${gross_cost_raw:,.0f}",
        "net_cost": f"${net_cost_raw:,.0f}",
        "itc_amount": f"${itc_raw:,.0f}",
        "payback": f"{payback_raw:.1f}",
        "monthly_bill": f"${monthly_bill:.0f}",
        "waiting_1yr_cost": f"${waiting_1yr:,.0f}",
        "waiting_3yr_cost": f"${waiting_3yr:,.0f}",
        "bills_10yr_total": f"${bills_10yr:,.0f}",
        "bills_25yr_total": f"${bills_25yr:,.0f}",
        "net_profit_25yr": f"${net_profit_25yr:,.0f}",
        "free_years": free_years,
        "monthly_bill_10yr": f"{bill_10yr_mo:.0f}",
    }


def fill_template(text: str, ctx: dict) -> str:
    """Fill {variable} placeholders. Leave unfilled vars as-is."""
    for key, val in ctx.items():
        text = text.replace("{" + key + "}", str(val))
    return text


def generate_drip_campaign(lead: dict, stage: str = "new", monthly_bill: float = 175.0,
                            rep_name: str = "Your Solar Rep", rep_phone: str = "602-555-0100",
                            company: str = "Elevate Solar", contact_name: str = "",
                            email: str = "") -> dict:
    """
    Generate a complete drip campaign for a lead at a given pipeline stage.
    Returns dict with messages[], metadata, and csv_rows[] for GHL import.
    """
    stage = stage.lower()
    if stage not in CAMPAIGNS:
        stage = "new"

    ctx = build_context(lead, monthly_bill, rep_name, rep_phone, company, contact_name, email)
    steps = CAMPAIGNS[stage]
    today = datetime.now()

    messages = []
    for step in steps:
        send_date = (today + timedelta(days=step["day"])).strftime("%Y-%m-%d")
        subject = fill_template(step.get("subject", ""), ctx)
        body = fill_template(step["body"], ctx)

        messages.append({
            "day": step["day"],
            "send_date": send_date,
            "channel": step["channel"],
            "goal": step["goal"],
            "subject": subject,
            "body": body,
        })

    # GHL-compatible CSV rows (one row per message)
    csv_rows = []
    for msg in messages:
        csv_rows.append({
            "contact_name": ctx["contact_name"],
            "contact_email": ctx["email"],
            "address": ctx["address"],
            "stage": stage,
            "day": msg["day"],
            "send_date": msg["send_date"],
            "channel": msg["channel"].upper(),
            "goal": msg["goal"],
            "subject": msg["subject"],
            "body": msg["body"],
            "lead_score": ctx["score"],
            "grade": ctx["grade"],
            "priority": ctx["priority"],
            "savings_yr1": ctx["savings_yr1"],
            "itc_amount": ctx["itc_amount"],
            "payback_years": ctx["payback"],
        })

    return {
        "stage": stage,
        "stage_label": STAGE_INTRO.get(stage, stage),
        "contact_name": ctx["contact_name"],
        "address": ctx["address"],
        "lead_score": ctx["score"],
        "grade": ctx["grade"],
        "message_count": len(messages),
        "sms_count": sum(1 for m in messages if m["channel"] == "sms"),
        "email_count": sum(1 for m in messages if m["channel"] == "email"),
        "total_days": max(m["day"] for m in messages) if messages else 0,
        "rep_name": rep_name,
        "rep_phone": rep_phone,
        "company": company,
        "messages": messages,
        "csv_rows": csv_rows,
        "context": ctx,
        "generated_at": datetime.now().isoformat(),
    }


def export_csv(campaign: dict) -> str:
    """Return GHL-importable CSV string."""
    if not campaign["csv_rows"]:
        return ""
    output = io.StringIO()
    fieldnames = list(campaign["csv_rows"][0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(campaign["csv_rows"])
    return output.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Terminal renderer
# ─────────────────────────────────────────────────────────────────────────────

def render_campaign(campaign: dict, color: bool = True) -> str:
    def c(code, text):
        return f"{code}{text}{RESET}" if color else text

    lines = []
    lines.append(c(BOLD + CYAN, "━" * 72))
    lines.append(c(BOLD + WHITE, f"  90-DAY DRIP CAMPAIGN — {campaign['stage'].upper()} STAGE"))
    lines.append(c(BOLD + CYAN, "━" * 72))
    lines.append(c(GRAY, f"  {campaign['stage_label']}"))
    lines.append("")
    lines.append(c(WHITE, f"  Contact:  {campaign['contact_name']}"))
    lines.append(c(WHITE, f"  Address:  {campaign['address']}"))
    lines.append(c(WHITE, f"  Score:    {campaign['lead_score']}/100 — {campaign['grade']}"))
    lines.append(c(WHITE, f"  Messages: {campaign['message_count']} total "
                          f"({campaign['email_count']} email, {campaign['sms_count']} SMS) "
                          f"over {campaign['total_days']} days"))
    lines.append(c(WHITE, f"  Rep:      {campaign['rep_name']} | {campaign['rep_phone']} | {campaign['company']}"))
    lines.append("")

    for i, msg in enumerate(campaign["messages"], 1):
        ch = msg["channel"].upper()
        ch_color = CYAN if ch == "SMS" else BLUE
        lines.append(c(BOLD + YELLOW, f"  {'─' * 66}"))
        lines.append(c(BOLD + WHITE, f"  Step {i} of {campaign['message_count']} — "
                                      f"Day {msg['day']} | ") +
                      c(BOLD + ch_color, ch) +
                      c(GRAY, f" | {msg['send_date']}"))
        lines.append(c(GRAY, f"  Goal: {msg['goal']}"))
        if msg.get("subject"):
            lines.append(c(MAGENTA, f"  Subject: {msg['subject']}"))
        lines.append("")
        # Word-wrap body
        body_lines = msg["body"].split("\n")
        for bl in body_lines:
            if len(bl) <= 70:
                lines.append(c(WHITE, f"  {bl}"))
            else:
                import textwrap
                for wrapped in textwrap.wrap(bl, 68):
                    lines.append(c(WHITE, f"  {wrapped}"))
        lines.append("")

    lines.append(c(BOLD + CYAN, "━" * 72))
    lines.append(c(GREEN, f"  ✅ {campaign['message_count']} messages ready — "
                          f"export CSV for GHL import with --format csv"))
    lines.append(c(BOLD + CYAN, "━" * 72))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="90-Day Lead Nurture Drip Campaign Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/drip_campaign.py --lead-id 1
  python scripts/drip_campaign.py --address "1905 E Marquette Dr, Gilbert AZ" --bill 175
  python scripts/drip_campaign.py --lead-id 2 --stage proposed
  python scripts/drip_campaign.py --lead-id 1 --format csv > campaign.csv
  python scripts/drip_campaign.py --address "..." --stage contacted --format json
        """
    )
    parser.add_argument("--lead-id", type=int, help="Pipeline lead ID (from scripts/pipeline.py)")
    parser.add_argument("--address", help="Home address (uses API / cache)")
    parser.add_argument("--bill", type=float, default=175.0, help="Monthly electric bill (default: $175)")
    parser.add_argument("--stage", choices=list(CAMPAIGNS.keys()), help="Pipeline stage (auto-detected from lead-id)")
    parser.add_argument("--contact", default="", help="Contact name (e.g., 'John Smith')")
    parser.add_argument("--email", default="", help="Contact email")
    parser.add_argument("--rep-name", default="Your Solar Rep", help="Rep name for messages")
    parser.add_argument("--rep-phone", default="602-555-0100", help="Rep phone number")
    parser.add_argument("--company", default="Elevate Solar", help="Company name")
    parser.add_argument("--format", choices=["text", "json", "csv"], default="text", help="Output format")
    parser.add_argument("--no-color", action="store_true", help="Plain text output")
    parser.add_argument("--no-enrich", action="store_true", help="Skip API call, use bill-estimate only")
    parser.add_argument("--list-stages", action="store_true", help="List available stages and exit")
    args = parser.parse_args()

    if args.list_stages:
        for stage, label in STAGE_INTRO.items():
            print(f"  {stage:12s} — {label}")
        return

    lead = {}
    contact_name = args.contact
    email_addr = args.email
    stage = args.stage

    # Load from pipeline DB if lead-id given
    if args.lead_id:
        try:
            from scripts.pipeline import PipelineCRM
            db = PipelineCRM()
            rec = db.get_lead(args.lead_id)
            if not rec:
                print(f"❌ Lead ID {args.lead_id} not found in pipeline.", file=sys.stderr)
                sys.exit(1)
            address_str = rec.get("address", "")
            contact_name = contact_name or rec.get("contact_name", "")
            email_addr = email_addr or rec.get("email", "")
            monthly_bill = args.bill if args.bill != 175.0 else rec.get("monthly_bill", 175.0)
            stage = stage or rec.get("stage", "new")
            if not args.no_enrich and address_str:
                from core.solar import enrich_lead
                lead = enrich_lead(address_str, monthly_bill=monthly_bill)
            else:
                lead = {"address": address_str}
            lead["monthly_bill"] = monthly_bill
        except Exception as e:
            print(f"⚠️  Could not load pipeline lead: {e}", file=sys.stderr)
            lead = {}
            stage = stage or "new"
    elif args.address:
        if not args.no_enrich:
            try:
                from core.solar import enrich_lead
                lead = enrich_lead(args.address, monthly_bill=args.bill)
            except Exception as e:
                print(f"⚠️  Could not enrich: {e}", file=sys.stderr)
                lead = {"address": args.address}
        else:
            lead = {"address": args.address}
        stage = stage or "new"
    else:
        parser.print_help()
        sys.exit(0)

    stage = stage or "new"
    monthly_bill = args.bill

    campaign = generate_drip_campaign(
        lead, stage=stage, monthly_bill=monthly_bill,
        rep_name=args.rep_name, rep_phone=args.rep_phone,
        company=args.company, contact_name=contact_name, email=email_addr
    )

    if args.format == "json":
        out = {k: v for k, v in campaign.items() if k != "csv_rows"}
        print(json.dumps(out, indent=2))
    elif args.format == "csv":
        print(export_csv(campaign))
    else:
        print(render_campaign(campaign, color=not args.no_color))


if __name__ == "__main__":
    main()
