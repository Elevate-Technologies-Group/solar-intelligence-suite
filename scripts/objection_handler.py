#!/usr/bin/env python3
"""
Solar Objection Handler — Data-Personalized Rebuttal Script Generator
Generates closing rebuttals for 10 common solar objections.
When an address is provided, injects real solar data for credibility.

Usage:
    python scripts/objection_handler.py "too expensive" --bill 175
    python scripts/objection_handler.py "roof" --address "1905 E Marquette Dr, Gilbert AZ" --bill 175
    python scripts/objection_handler.py --list
    python scripts/objection_handler.py --json "not interested"
"""

import sys, os, json, argparse, textwrap
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─── ANSI colors ─────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
BG_BLUE   = "\033[44m"
BG_GREEN  = "\033[42m"
BG_RED    = "\033[41m"

# ─── OBJECTION DATABASE ───────────────────────────────────────────────────────
# Each objection has:
#   keywords    — trigger words to detect this objection
#   title       — display name
#   hook        — opening 1-liner for the rep to say first
#   rebuttals   — list of talking point templates (use {var} for personalization)
#   transition  — closing line to pivot toward next step
#   data_vars   — which lead fields feed into this objection

OBJECTIONS = [
    {
        "id": "too_expensive",
        "title": "\"It's too expensive\" / Up-front cost",
        "keywords": ["expensive", "cost", "price", "afford", "money", "cheap", "pay", "upfront", "up-front", "budget"],
        "hook": "I totally get that — when I show people the gross cost, they feel the same way. But let me show you what the actual out-of-pocket looks like after incentives.",
        "rebuttals": [
            "💰 After the 30% federal ITC alone, the net cost drops from {gross_cost} to {net_cost} — that's real money back in your pocket in April.",
            "📉 In Arizona, you also get a state income tax credit (up to $1,000), sales tax exemption on equipment, and APS/SRP utility rebates — stacking all of these, your effective cost is often {effective_cost_note}.",
            "📆 Your payback period is only {payback_yr} years — after that, the electricity is essentially free for the remaining {remaining_yrs} years of the system's 25-year life.",
            "🏦 Most of our customers don't pay cash. With a {loan_rate}% solar loan, your monthly payment is around {loan_payment}/mo — and your current electric bill is {monthly_bill}/mo. You'd be cash-flow positive from Day 1.",
            "💡 Put another way: you're currently paying {monthly_bill}/mo to the utility company and building zero equity. With solar, that same monthly spend builds an asset on your home that increases property value.",
        ],
        "transition": "Would it help to see the full financing breakdown side-by-side with your current bill so you can see exact dollar-for-dollar?",
    },
    {
        "id": "not_interested",
        "title": "\"Not interested\" / No engagement",
        "keywords": ["not interested", "no thanks", "pass", "not looking", "don't need", "don't want", "go away", "busy"],
        "hook": "Totally fair — I'm not here to sell you anything today. I'm actually just showing homeowners on this street what their numbers look like. Takes about 60 seconds.",
        "rebuttals": [
            "📊 I ran your address through our satellite analysis tool — your roof scores {score}/100 for solar. That's {grade} tier. I'd hate for you to miss out without at least seeing the numbers.",
            "💸 Your neighbors at 2-3 homes down the street are saving an average of {avg_savings}/year. That's real money staying in the neighborhood instead of going to APS.",
            "⏰ The 30% federal tax credit is locked in through 2032, but installation waitlists are already 6–8 weeks out. Even if you're not ready today, it costs nothing to get your home qualified.",
            "🏡 A solar system on your home increases property value by an average of 4%+ (Zillow/Lawrence Berkeley Lab data). You don't have to want solar — but you might want that equity.",
            "📅 What if I just texted you the analysis report? No calls, no pressure. If the numbers ever make sense, you'll have it. If not, delete it.",
        ],
        "transition": "Can I just pull up your 60-second satellite analysis right here? If the numbers don't excite you, I'll be on my way — deal?",
    },
    {
        "id": "think_about_it",
        "title": "\"Let me think about it\" / Stalling",
        "keywords": ["think", "consider", "not now", "later", "someday", "wait", "not ready", "not sure", "maybe", "discuss"],
        "hook": "Of course — this is a real decision and it deserves thought. Can I show you one thing before you go? It'll actually help you think about it more clearly.",
        "rebuttals": [
            "📅 Every month you wait costs you {monthly_cost_of_waiting} — that's {monthly_bill} in bills you'll never recover, plus another month of rising rates.",
            "📈 APS and SRP have raised rates an average of 3–5%/year over the past decade. Waiting 12 months means your Year 1 savings baseline starts {escalated_bill}/mo higher.",
            "💵 Waiting 12 months on this home means leaving {annual_savings_yr1} in uncaptured savings on the table — money you'll never get back.",
            "🏦 Financing rates are dynamic. Today's locked-in solar loan rates won't necessarily be available in 6 months if the credit market shifts.",
            "📋 There's actually nothing to lose by getting approved now — approval takes 2 minutes, doesn't affect your credit score (soft pull only), and you can still say no after seeing the final proposal.",
        ],
        "transition": "What specifically do you want to think through? Let me address it right now so you have everything you need to make a confident decision.",
    },
    {
        "id": "moving_soon",
        "title": "\"We're moving soon\" / Won't be here long enough",
        "keywords": ["moving", "relocating", "selling", "not staying", "temporary", "renting", "rent", "lease", "landlord"],
        "hook": "Actually, that makes solar even more urgent — let me explain why sellers with solar are getting a major advantage right now.",
        "rebuttals": [
            "🏡 Homes with solar sell for 4–6% more on average (Lawrence Berkeley National Lab study of 23,000+ homes). On a {home_value_note} home, that's an additional $12,000–$18,000 at closing.",
            "⚡ Solar homes sell 20% faster than comparable non-solar homes — buyers are actively seeking lower utility costs, especially in Phoenix's climate.",
            "💰 The solar system adds to your home's appraised value — and appraisers use a 20:1 income multiplier. {annual_savings_yr1}/year in savings = ~{property_value_add} in added value.",
            "📜 Your system warranty (25 years) transfers to the new buyer — it's a selling feature, not a liability. You're gifting them {payback_yr} years of savings.",
            "📊 Even if you sell in 2 years, your net gain from home value increase alone typically exceeds the net cost of the system — you come out ahead even before counting electricity savings.",
        ],
        "transition": "Would you like to see a quick breakdown of how much value this adds to your home at your expected sale price?",
    },
    {
        "id": "roof_concerns",
        "title": "\"My roof is too old / shaded / not right\"",
        "keywords": ["roof", "shade", "tree", "north", "south", "old roof", "tiles", "flat", "complex", "direction", "facing"],
        "hook": "Great question — roof suitability is one of the first things we check. I actually already ran your roof through our satellite analysis. Let me show you what we found.",
        "rebuttals": [
            "🛰️ Our satellite data shows your roof has {panel_count} viable solar panels worth of usable area with {segment_count} roof segments — that's {grade} tier.",
            "☀️ Your roof receives {sunshine_hrs} peak sun hours per day — Phoenix averages 5.8, so {sunshine_comparison}.",
            "🌳 Shading is already factored into our analysis. The system we'd design only uses the unshaded segments, so partial shade on one side of the roof doesn't necessarily affect production.",
            "🔧 If your roof needs work first, many installers offer a bundle: roof repair or replacement + solar installation — and the roof portion can even be included in the solar financing at solar loan rates (lower than a home equity loan).",
            "📐 Flat roofs, tile roofs, and metal roofs are all compatible with modern racking systems. The {segment_count}-segment layout on your home would be designed for your specific roof type.",
        ],
        "transition": "Want me to walk you through the actual satellite image of your roof so you can see exactly what we're working with?",
    },
    {
        "id": "hoa",
        "title": "\"My HOA won't allow it\" / HOA restrictions",
        "keywords": ["hoa", "homeowners association", "association", "approval", "community", "rules", "neighborhood"],
        "hook": "HOA concerns come up a lot in Arizona — here's the good news: Arizona law actually limits what HOAs can do about solar.",
        "rebuttals": [
            "⚖️ Arizona Revised Statute §33-1816 explicitly prohibits HOAs from banning solar panels. They can regulate aesthetics (color, placement) but cannot prevent installation outright.",
            "📋 We handle HOA approvals as part of our process. Our team prepares the submission package, architectural review forms, and spec sheets — you don't have to navigate that yourself.",
            "🏘️ Over 70% of our installations in HOA communities are approved within 2 weeks. We have templates specifically for APS territory communities.",
            "🎨 Modern solar panels are lower profile and more aesthetically integrated than ever — many HOAs that previously opposed solar have passed approval standards because new systems don't visually impact streetscape.",
            "📝 Even if your HOA required specific panel placement, we'd design around those constraints while still maximizing your {annual_savings_yr1}/year in savings.",
        ],
        "transition": "Would it help if I showed you the Arizona statute language? I can also tell you which HOA board members in this zip code have already approved installations.",
    },
    {
        "id": "reliability",
        "title": "\"Solar doesn't work / reliability concerns\"",
        "keywords": ["work", "reliable", "cloudy", "night", "dark", "outage", "power", "backup", "battery", "blackout", "storm", "rain", "overcast"],
        "hook": "Valid concern — let me show you what actually happens at night, on cloudy days, and during outages. The answer might surprise you.",
        "rebuttals": [
            "☀️ Phoenix averages {sunshine_hrs} peak sun hours per day — one of the highest in the country. Even on cloudy days, panels produce 10–25% of rated capacity (diffuse light still works).",
            "🔄 Net metering: during the day, you produce more than you use and bank credits with APS/SRP. At night, you draw those credits back — it's like a solar savings account.",
            "🔋 Battery storage (like Tesla Powerwall or Enphase IQ Battery) can be added to keep your home powered during outages. Many of our customers go fully grid-independent.",
            "📊 Your system is designed with {panel_count} panels producing {annual_production_kwh} kWh/year — that's a {solar_offset}% offset of your current consumption. Even in the lowest-production months, you'll see your bill drop significantly.",
            "🛡️ Panels are warrantied for 25 years of production (at least 80% of rated output guaranteed). Inverters carry 10–12 year warranties. This tech has been mainstream for 20+ years.",
        ],
        "transition": "Would it help to see your projected month-by-month production chart so you can see exactly how much you'd generate in December vs June?",
    },
    {
        "id": "salesperson_distrust",
        "title": "\"I don't trust solar companies\" / Scam concerns",
        "keywords": ["scam", "trust", "sketchy", "neighbor", "rip off", "fraud", "fake", "heard bad", "problems", "gone out", "bankrupt", "complaints"],
        "hook": "I completely understand the skepticism — there have been some bad actors in this industry. Let me be transparent about exactly how this works and what protections you have.",
        "rebuttals": [
            "🔍 Legitimate solar companies are licensed contractors (ROC license in AZ), bonded, and insured. Ask to see the ROC number — ours is on every proposal and verifiable online in 30 seconds.",
            "📋 Every incentive claim we make is IRS/DOE-documented. The 30% federal ITC is codified in the Inflation Reduction Act (Public Law 117-169). It's not a promotional offer — it's tax law.",
            "🤝 We provide a written production guarantee. If the system doesn't produce what we projected, we compensate you for the shortfall. That's something a scam company can't offer.",
            "🏘️ I can connect you with {score} out of 100 scored customers in this neighborhood who have already installed — you can talk to real homeowners on this street about their experience.",
            "📄 Nothing gets signed until you've reviewed the full contract, utility interconnection agreement, and proposal with our project manager. You have a 3-day right of rescission on any signed contract in Arizona.",
        ],
        "transition": "Would you feel more comfortable if I connected you with one of our recent installs in your zip code — a real neighbor you can call?",
    },
    {
        "id": "already_have_quote",
        "title": "\"I already got a quote\" / Competitor comparison",
        "keywords": ["quote", "quoted", "another company", "competitor", "sunrun", "tesla", "sunpower", "vivint", "other", "comparing", "already"],
        "hook": "Great — you're doing your homework. Can I ask what you were quoted? I want to make sure you're comparing apples to apples, because the numbers vary a lot based on assumptions.",
        "rebuttals": [
            "📊 Key things to compare: $/watt installed (industry range: $2.50–$4.00/W), panel wattage and brand, inverter type (string vs microinverter vs power optimizer), monitoring platform, and warranty terms.",
            "🔢 Our analysis shows your home needs a {system_kw}kW system. If another quote shows a significantly smaller or larger system, ask them how they modeled your consumption and shading.",
            "💡 Microinverters (Enphase) vs string inverters (SolarEdge) matter a lot on a {segment_count}-segment roof — shading on one panel doesn't kill the whole array with microinverters.",
            "📝 Ask the other company for their production guarantee in writing. Ask if their savings projections assume a rate escalation — and what rate. Many quotes look great on paper because they assume a 5% annual rate increase that may not materialize.",
            "🏆 Our score for your home is {score}/100 — a {grade} rating. Whatever you decide, make sure any quote you receive accounts for the {sunshine_hrs} peak sun hours your specific roof gets.",
        ],
        "transition": "I'd be happy to do a side-by-side comparison of their quote vs ours — on paper, right now. Want to grab it?",
    },
    {
        "id": "spouse_partner",
        "title": "\"Need to talk to my spouse / partner\"",
        "keywords": ["spouse", "wife", "husband", "partner", "together", "discuss", "both", "ask", "family", "kids", "parents"],
        "hook": "Absolutely — this is a shared decision and it should be. Is there any chance your spouse could join us for 10 minutes? Or better yet, let me set up a time when you're both available.",
        "rebuttals": [
            "📱 I can send a summary text or email to both of you right now — that way your spouse has the same information you do and you're looking at the same numbers.",
            "💰 The main question most spouses have is: does this save money or cost money? The short answer for your home: you'd save {annual_savings_yr1}/year — {monthly_savings}/month — with a {payback_yr}-year payback.",
            "🏡 The property value angle often resonates with the other decision-maker — solar adds ~4–6% to home value, which on most Phoenix homes is $15,000–$25,000 in equity.",
            "📊 I can prepare a one-page visual summary — shows the before/after bill, incentive breakdown, financing payment vs current bill, and 10-year savings projection. Very digestible.",
            "📅 Can we schedule a 20-minute call with both of you this week? I'll come back with a custom proposal — no obligation. If you both say no after seeing the full picture, I understand completely.",
        ],
        "transition": "What's the best way to include them — should I come back at a time they're home, or would a 3-way call work better?",
    },
]

# ─── MATCH OBJECTION ──────────────────────────────────────────────────────────

def find_objection(query: str) -> dict | None:
    """Find the best matching objection from query string or index."""
    q = query.lower().strip()

    # Try numeric index first
    try:
        idx = int(q) - 1
        if 0 <= idx < len(OBJECTIONS):
            return OBJECTIONS[idx]
    except ValueError:
        pass

    # Try ID match
    for obj in OBJECTIONS:
        if q == obj["id"]:
            return obj

    # Try keyword match (score by number of matching keywords)
    scores = []
    for obj in OBJECTIONS:
        score = sum(1 for kw in obj["keywords"] if kw in q)
        scores.append((score, obj))
    scores.sort(key=lambda x: x[0], reverse=True)

    if scores and scores[0][0] > 0:
        return scores[0][1]

    # Fuzzy: check if any keyword is a substring of any word in query
    for obj in OBJECTIONS:
        for kw in obj["keywords"]:
            if kw in q or any(w in kw for w in q.split() if len(w) > 3):
                return obj

    return None

# ─── PERSONALISE REBUTTALS ────────────────────────────────────────────────────

def _fmt_usd(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except Exception:
        return str(v)

def _fmt_num(v, decimals=1) -> str:
    try:
        return f"{float(v):.{decimals}f}"
    except Exception:
        return str(v)

def build_context(lead: dict | None, monthly_bill: float = 175.0) -> dict:
    """Build substitution context from a lead dict + bill."""
    ctx = {
        "monthly_bill": _fmt_usd(monthly_bill),
        "grade": "A+",
        "score": "82",
        "payback_yr": "7.5",
        "remaining_yrs": "17.5",
        "annual_savings_yr1": _fmt_usd(monthly_bill * 12 * 0.90),
        "monthly_savings": _fmt_usd(monthly_bill * 0.90),
        "sunshine_hrs": "5.8",
        "sunshine_comparison": "your roof is right at the Phoenix average — excellent production",
        "panel_count": "22",
        "segment_count": "3",
        "system_kw": "6.4",
        "solar_offset": "95",
        "annual_production_kwh": "10,500",
        "gross_cost": "$21,000",
        "net_cost": "$14,700",
        "effective_cost_note": "well under $15,000 after all programs stack",
        "loan_rate": "5.99",
        "loan_payment": _fmt_usd(monthly_bill * 0.85),
        "escalated_bill": _fmt_usd(monthly_bill * 1.035),
        "monthly_cost_of_waiting": _fmt_usd(monthly_bill + monthly_bill * 12 * 0.90 / 12),
        "home_value_note": "$400,000",
        "property_value_add": _fmt_usd(monthly_bill * 12 * 20),
    }

    if not lead or lead.get("error"):
        return ctx

    # Support both flat schema (core.solar.enrich_lead) and nested API response
    # Flat schema keys: lead_score, lead_grade, annual_savings_yr1_usd, payback_years,
    #                   sunshine_hours_per_year, panels_recommended, system_size_kw, etc.
    # Nested schema keys: lead_scoring.score, financials.annual_savings_yr1, etc.

    # --- Score / Grade ---
    gr = (lead.get("lead_grade")
          or lead.get("grade")
          or (lead.get("lead_scoring") or {}).get("grade", "A+"))
    sc = (lead.get("lead_score")
          or lead.get("score")
          or (lead.get("lead_scoring") or {}).get("score", 82))
    ctx["grade"] = str(gr)
    ctx["score"] = str(sc)

    # --- Payback ---
    payback = (lead.get("payback_years")
               or (lead.get("financials") or {}).get("payback_years"))
    if payback:
        ctx["payback_yr"] = _fmt_num(payback)
        ctx["remaining_yrs"] = _fmt_num(max(0, 25 - float(payback)))

    # --- Annual savings ---
    ann_sav = (lead.get("annual_savings_yr1_usd")
               or (lead.get("financials") or {}).get("annual_savings_yr1"))
    if ann_sav:
        ctx["annual_savings_yr1"] = _fmt_usd(ann_sav)
        ctx["monthly_savings"] = _fmt_usd(float(ann_sav) / 12)

    # --- Sunshine hours ---
    sun_annual = (lead.get("sunshine_hours_per_year")
                  or (lead.get("roof_analysis") or {}).get("max_sunshine_hours_per_year"))
    if sun_annual:
        daily = float(sun_annual) / 365
        ctx["sunshine_hrs"] = _fmt_num(daily)
        if daily >= 6.0:
            ctx["sunshine_comparison"] = "above the Phoenix average — your roof is in an excellent solar zone"
        elif daily >= 5.5:
            ctx["sunshine_comparison"] = "right at the Phoenix average — solid production expected"
        else:
            ctx["sunshine_comparison"] = "slightly below average due to shading factors already accounted for"

    # --- Panels / segments / system size ---
    panels = (lead.get("panels_recommended")
              or lead.get("max_panels_possible")
              or (lead.get("roof_analysis") or {}).get("max_array_panels_count"))
    if panels:
        ctx["panel_count"] = str(panels)

    segs = lead.get("roof_segments")
    if segs is None:
        segs_list = (lead.get("roof_analysis") or {}).get("roof_segment_stats", [])
        if segs_list:
            ctx["segment_count"] = str(len(segs_list))
    elif isinstance(segs, int):
        ctx["segment_count"] = str(segs)
    elif hasattr(segs, "__len__"):
        ctx["segment_count"] = str(len(segs))

    kw = (lead.get("system_size_kw")
          or (lead.get("roof_analysis") or {}).get("max_array_size_kw"))
    if kw:
        ctx["system_kw"] = _fmt_num(kw, 1)

    offset = (lead.get("offset_pct")
              or (lead.get("financials") or {}).get("solar_offset_pct"))
    if offset:
        ctx["solar_offset"] = _fmt_num(float(offset), 0)

    annual_kwh = lead.get("annual_kwh_produced")
    if annual_kwh:
        ctx["annual_production_kwh"] = f"{float(annual_kwh):,.0f}"
    elif sun_annual and kw:
        ctx["annual_production_kwh"] = f"{float(sun_annual) * float(kw) * 0.78:,.0f}"

    # --- Costs ---
    gross = (lead.get("gross_cost_usd")
             or (lead.get("financials") or {}).get("gross_system_cost"))
    if gross:
        ctx["gross_cost"] = _fmt_usd(gross)
        ctx["net_cost"] = _fmt_usd(float(gross) * 0.70)
        ctx["effective_cost_note"] = f"around {_fmt_usd(float(gross) * 0.60)} after all AZ incentives stack"

    net = (lead.get("net_cost_usd")
           or (lead.get("financials") or {}).get("net_system_cost"))
    if net:
        ctx["net_cost"] = _fmt_usd(net)
        ctx["loan_payment"] = _fmt_usd(float(net) / (12 * 20) * 1.12)

    ctx["monthly_bill"] = _fmt_usd(monthly_bill)
    try:
        ann_val = float(ctx["annual_savings_yr1"].replace("$","").replace(",",""))
    except Exception:
        ann_val = monthly_bill * 12 * 0.9
    ctx["monthly_cost_of_waiting"] = _fmt_usd(monthly_bill + ann_val / 12)
    ctx["escalated_bill"] = _fmt_usd(monthly_bill * 1.035)

    return ctx

def personalise(text: str, ctx: dict) -> str:
    """Fill in {var} placeholders, leave unfilled ones as readable defaults."""
    for k, v in ctx.items():
        text = text.replace("{" + k + "}", str(v))
    # Remove unfilled placeholders
    import re
    text = re.sub(r"\{[a-z_]+\}", "[data unavailable]", text)
    return text

# ─── CORE FUNCTION ────────────────────────────────────────────────────────────

def get_rebuttals(objection_query: str, lead: dict = None, monthly_bill: float = 175.0) -> dict:
    """
    Return a structured objection handler response.

    Args:
        objection_query: keyword, objection number, or free-text
        lead:            enriched lead dict (optional, from core.solar.enrich_lead)
        monthly_bill:    assumed monthly electric bill

    Returns dict:
        {
          objection_id, title, hook, rebuttals: [], transition, talking_points: [],
          context_used: bool, address: str|None, lead_score: int|None, grade: str|None
        }
    """
    obj = find_objection(objection_query)
    if not obj:
        return {
            "error": f"No objection matched for: '{objection_query}'",
            "available": [o["title"] for o in OBJECTIONS],
        }

    ctx = build_context(lead, monthly_bill)

    return {
        "objection_id":   obj["id"],
        "title":          obj["title"],
        "hook":           obj["hook"],
        "rebuttals":      [personalise(r, ctx) for r in obj["rebuttals"]],
        "transition":     personalise(obj["transition"], ctx),
        "talking_points": [personalise(r, ctx) for r in obj["rebuttals"]],  # alias
        "context_used":   lead is not None and not (lead or {}).get("error"),
        "address":        ((lead or {}).get("formatted_address")
                           or (lead or {}).get("address")),
        "lead_score":     ((lead or {}).get("lead_score")
                           or (lead or {}).get("lead_scoring", {}).get("score")),
        "grade":          ((lead or {}).get("lead_grade")
                           or (lead or {}).get("lead_scoring", {}).get("grade")),
        "monthly_bill":   monthly_bill,
        "context":        ctx,
    }

def list_objections() -> list[dict]:
    return [{"num": i+1, "id": o["id"], "title": o["title"], "keywords": o["keywords"][:5]}
            for i, o in enumerate(OBJECTIONS)]

# ─── TERMINAL DISPLAY ─────────────────────────────────────────────────────────

def print_objection_report(result: dict, color: bool = True):
    def c(code, text):
        return f"{code}{text}{RESET}" if color else text

    if "error" in result:
        print(c(RED, f"\n✗ {result['error']}"))
        print(c(DIM, "\nAvailable objections:"))
        for t in result.get("available", []):
            print(c(DIM, f"  • {t}"))
        return

    print()
    print(c(BG_BLUE + BOLD, f"  ⚡ SOLAR OBJECTION HANDLER  "))
    print(c(BOLD, f"\n  Objection: {result['title']}"))

    if result.get("address"):
        score = result.get("lead_score", "N/A")
        grade = result.get("grade", "")
        print(c(CYAN, f"  Address:   {result['address']}"))
        print(c(GREEN, f"  Lead:      Score {score}/100 — Grade {grade}"))
    else:
        print(c(YELLOW, f"  Mode:      Bill-only estimate (${result.get('monthly_bill', 175):.0f}/mo)"))

    # Hook
    print()
    print(c(BOLD + YELLOW, "── OPENING HOOK ─────────────────────────────────────────────────────"))
    for line in textwrap.wrap(result["hook"], 78):
        print(c(YELLOW, f"  \"{line}\""))

    # Rebuttals
    print()
    print(c(BOLD + GREEN, "── TALKING POINTS ───────────────────────────────────────────────────"))
    for i, rb in enumerate(result["rebuttals"], 1):
        # First char is likely an emoji
        lines = textwrap.wrap(rb, 76)
        for j, line in enumerate(lines):
            prefix = "  " if j > 0 else "  "
            print(c(WHITE if j == 0 else DIM, f"{prefix}{line}"))
        print()

    # Transition
    print(c(BOLD + CYAN, "── CLOSING PIVOT ────────────────────────────────────────────────────"))
    for line in textwrap.wrap(result["transition"], 78):
        print(c(CYAN, f"  ➜ {line}"))

    print()
    print(c(DIM, f"  Tip: Use the --address flag with the homeowner's address for personalized data."))
    print()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Solar Objection Handler — data-personalized rebuttal scripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python scripts/objection_handler.py "too expensive"
  python scripts/objection_handler.py "let me think about it" --bill 195
  python scripts/objection_handler.py "roof" --address "1905 E Marquette Dr, Gilbert AZ" --bill 175
  python scripts/objection_handler.py --list
  python scripts/objection_handler.py 3 --bill 175 --json
"""
    )
    parser.add_argument("objection", nargs="?", default=None, help="Objection keyword, number (1-10), or phrase")
    parser.add_argument("--address", "-a", default=None, help="Homeowner address (enriches with real solar data)")
    parser.add_argument("--bill",    "-b", type=float, default=175.0, help="Monthly electric bill in USD (default: 175)")
    parser.add_argument("--list",    "-l", action="store_true", help="List all objection types")
    parser.add_argument("--json",    "-j", action="store_true", help="Output raw JSON")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")

    args = parser.parse_args()

    if args.list:
        objections = list_objections()
        if args.json:
            print(json.dumps(objections, indent=2))
            return
        print(f"\n{BOLD}Solar Objection Handler — 10 Rebuttals{RESET}\n")
        for o in objections:
            print(f"  {CYAN}{o['num']:2d}.{RESET} {BOLD}{o['title']}{RESET}")
            print(f"      {DIM}keywords: {', '.join(o['keywords'])}{RESET}")
        print()
        return

    if not args.objection:
        parser.print_help()
        return

    # Optionally enrich lead
    lead = None
    if args.address:
        try:
            from core.solar import enrich_lead
            print(f"{DIM}  Enriching {args.address}...{RESET}", end="\r", flush=True)
            lead = enrich_lead(args.address, monthly_bill=args.bill)
        except Exception as e:
            print(f"{YELLOW}  Warning: Could not enrich address — using bill-only mode ({e}){RESET}")

    result = get_rebuttals(args.objection, lead=lead, monthly_bill=args.bill)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    print_objection_report(result, color=not args.no_color)


if __name__ == "__main__":
    main()
