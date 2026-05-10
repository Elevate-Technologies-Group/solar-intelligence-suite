#!/usr/bin/env python3
"""
Morning Rep Briefing Generator
Pulls together: pipeline follow-ups, hot new leads, weather, and a motivational
pipeline snapshot — tells reps exactly who to call/knock today.

CLI:
    python scripts/morning_briefing.py
    python scripts/morning_briefing.py --rep "Jake Rivera" --city "Phoenix"
    python scripts/morning_briefing.py --json
    python scripts/morning_briefing.py --save  (writes cache/morning_briefing.txt)

Importable:
    from scripts.morning_briefing import generate_briefing
    result = generate_briefing(rep_name="Jake Rivera", city="Phoenix,AZ")
"""

import sys, os, json, sqlite3, glob, argparse, textwrap
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/root/solar-tools")

# ── ANSI ─────────────────────────────────────────────────────────────────────
GREEN   = "\033[92m"; YELLOW = "\033[93m"; RED    = "\033[91m"
CYAN    = "\033[96m"; WHITE  = "\033[97m"; GRAY   = "\033[90m"
BOLD    = "\033[1m";  RESET  = "\033[0m";  BLUE   = "\033[94m"
MAGENTA = "\033[95m"; ORANGE = "\033[33m"

def strip_ansi(s):
    import re
    return re.sub(r'\033\[[0-9;]*m', '', s)

def _c(text, color, use_color=True):
    return f"{color}{text}{RESET}" if use_color else text

def score_bar(score, width=20, use_color=True):
    filled = int(score / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    if score >= 80:   color = GREEN
    elif score >= 60: color = YELLOW
    else:             color = RED
    return _c(bar, color, use_color) + f" {score}/100"

# ── Weather fetch ─────────────────────────────────────────────────────────────
def fetch_weather(city="Phoenix,AZ"):
    """Fetch weather from wttr.in — free, no API key needed."""
    try:
        import urllib.request
        url = f"https://wttr.in/{city.replace(' ','+').replace(',','%2C')}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "solar-intelligence-suite/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        cw = data["current_condition"][0]
        today = data.get("weather", [{}])[0]
        hourly = today.get("hourly", [])
        # Peak afternoon hours for door knocking (hours 12-17)
        peak_hours = [h for h in hourly if int(h.get("time", "0")) in (1200, 1300, 1400, 1500, 1600, 1700)]
        max_uv = max((int(h.get("uvIndex", 0)) for h in peak_hours), default=0)
        return {
            "temp_f": int(cw.get("temp_F", 75)),
            "feels_like_f": int(cw.get("FeelsLikeF", 75)),
            "desc": cw.get("weatherDesc", [{}])[0].get("value", "Clear"),
            "uv_index": int(cw.get("uvIndex", 0)),
            "peak_uv": max_uv,
            "cloud_cover": int(cw.get("cloudcover", 0)),
            "humidity": int(cw.get("humidity", 30)),
            "wind_mph": int(cw.get("windspeedMiles", 0)),
            "max_temp_f": int(today.get("maxtempF", 80)),
            "min_temp_f": int(today.get("mintempF", 65)),
            "sunrise": today.get("astronomy", [{}])[0].get("sunrise", "6:00 AM"),
            "sunset":  today.get("astronomy", [{}])[0].get("sunset",  "7:00 PM"),
        }
    except Exception as e:
        return {"temp_f": 78, "feels_like_f": 78, "desc": "Unknown", "uv_index": 5,
                "peak_uv": 7, "cloud_cover": 10, "humidity": 25, "wind_mph": 5,
                "max_temp_f": 85, "min_temp_f": 65, "sunrise": "6:00 AM",
                "sunset": "7:00 PM", "error": str(e)}

def canvassing_score(weather):
    """0-10 score for how good a door-knocking day it is."""
    score = 10
    # Use max temp for forecasting — what it'll feel like in the field
    temp = weather.get("max_temp_f", weather.get("temp_f", 78))
    if temp > 108: score -= 8
    elif temp > 103: score -= 6
    elif temp > 98: score -= 4
    elif temp > 92: score -= 2
    if temp < 50: score -= 3
    if weather.get("wind_mph", 0) > 20: score -= 2
    if weather.get("cloud_cover", 0) > 70: score -= 1
    if weather.get("humidity", 30) > 75: score -= 1
    return max(0, min(10, score))

def canvassing_label(score):
    if score >= 8: return ("GREAT", GREEN)
    elif score >= 6: return ("GOOD", YELLOW)
    elif score >= 4: return ("FAIR", ORANGE)
    else: return ("ROUGH", RED)

# ── Pipeline fetch ────────────────────────────────────────────────────────────
PIPELINE_DB = "/root/solar-tools/cache/pipeline.db"
STAGE_ORDER = ["new", "contacted", "qualified", "proposed", "closed_won", "closed_lost"]
STAGE_LABELS = {
    "new": "New",
    "contacted": "Contacted",
    "qualified": "Qualified",
    "proposed": "Proposed",
    "closed_won": "Won",
    "closed_lost": "Lost",
}

def fetch_pipeline_data():
    if not os.path.exists(PIPELINE_DB):
        return {"leads": [], "stats": {}}
    conn = sqlite3.connect(PIPELINE_DB)
    leads = []
    rows = conn.execute("""
        SELECT id, address, contact_name, phone, stage, lead_score, lead_grade,
               priority, yr1_savings, payback_yrs, itc_savings, monthly_bill,
               deal_value, updated_at, created_at, source
        FROM leads WHERE stage NOT IN ('closed_won','closed_lost')
        ORDER BY lead_score DESC, updated_at ASC
    """).fetchall()
    now = datetime.now(timezone.utc)
    for r in rows:
        (lid, address, cname, phone, stage, score, grade, priority, yr1, payback,
         itc, bill, deal, updated_at, created_at, source) = r
        # Days since last update
        try:
            upd = datetime.fromisoformat(updated_at.replace("Z","")).replace(tzinfo=timezone.utc)
            days_stale = (now - upd).days
        except:
            days_stale = 0
        # Get last note
        note_row = conn.execute(
            "SELECT note FROM notes WHERE lead_id=? ORDER BY created_at DESC LIMIT 1", (lid,)
        ).fetchone()
        last_note = note_row[0] if note_row else None
        leads.append({
            "id": lid, "address": address, "contact_name": cname, "phone": phone,
            "stage": stage, "score": score or 0, "grade": grade or "N/A",
            "priority": priority or "UNKNOWN", "yr1_savings": yr1 or 0,
            "payback_yrs": payback or 0, "itc": itc or 0, "bill": bill or 0,
            "deal_value": deal or 0, "days_stale": days_stale,
            "last_note": last_note, "created_at": created_at,
        })
    # Stats including closed
    won_row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(deal_value),0) FROM leads WHERE stage='closed_won'"
    ).fetchone()
    pipeline_row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(deal_value),0) FROM leads "
        "WHERE stage NOT IN ('closed_won','closed_lost') AND deal_value > 0"
    ).fetchone()
    total_leads = conn.execute("SELECT COUNT(*) FROM leads WHERE stage NOT IN ('closed_won','closed_lost')").fetchone()[0]
    conn.close()
    stats = {
        "won_count": won_row[0], "won_revenue": won_row[1],
        "pipeline_count": pipeline_row[0], "pipeline_value": pipeline_row[1],
        "total_active": total_leads,
    }
    return {"leads": leads, "stats": stats}

def categorize_leads(leads):
    """Sort leads into action buckets."""
    urgent   = []  # stale >5 days, not contacted
    followup = []  # contacted/qualified but stale >3 days
    nurture  = []  # proposed, keep warm
    fresh    = []  # new <2 days
    for l in leads:
        if l["stage"] == "proposed":
            nurture.append(l)
        elif l["stage"] in ("contacted", "qualified") and l["days_stale"] >= 3:
            followup.append(l)
        elif l["stage"] == "new" and l["days_stale"] >= 5:
            urgent.append(l)
        elif l["stage"] == "new" and l["days_stale"] < 2:
            fresh.append(l)
        else:
            followup.append(l)
    return {
        "urgent": sorted(urgent, key=lambda x: -x["score"]),
        "followup": sorted(followup, key=lambda x: -x["score"]),
        "nurture": sorted(nurture, key=lambda x: -x["score"]),
        "fresh": sorted(fresh, key=lambda x: -x["score"]),
    }

# ── Cache leads ───────────────────────────────────────────────────────────────
CACHE_DIR = "/root/solar-tools/cache"

def fetch_cached_leads(limit=8):
    """Find recent HOT/WARM leads from enrichment cache."""
    json_files = sorted(
        glob.glob(os.path.join(CACHE_DIR, "*.json")),
        key=os.path.getmtime, reverse=True
    )
    hot_leads = []
    seen = set()
    for fpath in json_files[:50]:  # scan newest 50 files
        try:
            data = json.load(open(fpath))
            # Could be a single lead or a territory scan
            if "leads" in data:
                candidates = data["leads"]
            elif "formatted_address" in data:
                candidates = [data]
            else:
                continue
            for lead in candidates:
                addr = lead.get("formatted_address") or lead.get("address", "")
                if not addr or addr in seen: continue
                if lead.get("error"): continue
                priority = lead.get("priority", "")
                score = lead.get("lead_score", 0)
                if priority in ("HOT", "WARM") and score >= 70:
                    hot_leads.append({
                        "address": addr,
                        "score": score,
                        "grade": lead.get("grade", "B"),
                        "priority": priority,
                        "yr1_savings": lead.get("annual_savings_yr1", 0),
                        "payback": lead.get("payback_years", 0),
                        "itc": lead.get("federal_itc_savings", 0),
                        "system_kw": lead.get("system_size_kw", 0),
                        "sun_hours": lead.get("annual_sunshine_hours", 0),
                        "talking_points": lead.get("talking_points", [])[:2],
                        "source_file": os.path.basename(fpath),
                    })
                    seen.add(addr)
                    if len(hot_leads) >= limit:
                        break
        except:
            continue
        if len(hot_leads) >= limit:
            break
    return sorted(hot_leads, key=lambda x: -x["score"])[:limit]

# ── Talking point snippet ─────────────────────────────────────────────────────
def short_talking_point(lead):
    if lead.get("yr1_savings", 0) > 0:
        return f"Est. ${lead['yr1_savings']:,.0f} year-one savings, {lead.get('payback',0):.1f}yr payback"
    if lead.get("score", 0):
        return f"Score {lead['score']}/100 {lead.get('grade','')}"
    return ""

# ── Main briefing builder ─────────────────────────────────────────────────────
def generate_briefing(rep_name="Solar Rep", city="Phoenix,AZ", use_color=True):
    """Build full morning briefing. Returns dict + formatted text."""
    now = datetime.now()
    date_str = now.strftime("%A, %B %-d, %Y")
    time_str = now.strftime("%-I:%M %p")

    # Gather data
    weather   = fetch_weather(city)
    pipe_data = fetch_pipeline_data()
    pl        = pipe_data["leads"]
    stats     = pipe_data["stats"]
    buckets   = categorize_leads(pl)
    new_leads = fetch_cached_leads(limit=6)
    cv_score  = canvassing_score(weather)
    cv_label, cv_color = canvassing_label(cv_score)

    # Build structured result
    result = {
        "generated_at": now.isoformat(),
        "rep_name": rep_name,
        "city": city,
        "date": date_str,
        "weather": weather,
        "canvassing_score": cv_score,
        "canvassing_label": cv_label,
        "pipeline_stats": stats,
        "action_items": {
            "urgent":   [l["address"] for l in buckets["urgent"]],
            "followup": [l["address"] for l in buckets["followup"]],
            "nurture":  [l["address"] for l in buckets["nurture"]],
            "fresh":    [l["address"] for l in buckets["fresh"]],
        },
        "hot_prospects": new_leads,
        "total_calls_today": len(buckets["urgent"]) + len(buckets["followup"]) + len(buckets["nurture"]),
    }

    # ── Build text report ────────────────────────────────────────────────────
    C = use_color
    lines = []

    def ln(t=""): lines.append(t)
    def h1(t): ln(_c("═" * 70, CYAN, C)); ln(_c(f"  {t}", BOLD+WHITE, C)); ln(_c("═" * 70, CYAN, C))
    def h2(t, color=CYAN): ln(""); ln(_c(f"── {t} ", color, C) + _c("─" * max(0, 67 - len(t)), GRAY, C))
    def bullet(t, indent=2): ln(" " * indent + t)

    # Header
    ln(_c("╔══════════════════════════════════════════════════════════════════════╗", CYAN, C))
    ln(_c("║     ☀  SOLAR INTELLIGENCE SUITE — MORNING BRIEFING  ☀             ║", BOLD+YELLOW, C))
    ln(_c("╚══════════════════════════════════════════════════════════════════════╝", CYAN, C))
    ln()
    ln(_c(f"  Good morning, {rep_name}!   {date_str}  ·  {time_str}", BOLD+WHITE, C))
    ln(_c(f"  Here's everything you need to crush it today.", GRAY, C))

    # Weather block
    h2("☁  TODAY'S CONDITIONS — " + city.split(",")[0].upper(), BLUE)
    temp = weather["temp_f"]
    desc = weather["desc"]
    uv   = weather.get("peak_uv", weather.get("uv_index", 0))
    wind = weather.get("wind_mph", 0)
    hi   = weather.get("max_temp_f", temp)
    lo   = weather.get("min_temp_f", temp)
    sr   = weather.get("sunrise", "6:00 AM")
    ss   = weather.get("sunset", "7:00 PM")

    # Canvassing recommendation
    cv_bar = "●" * cv_score + "○" * (10 - cv_score)
    bullet(_c(f"Weather:  {desc}, {temp}°F  (H {hi}° / L {lo}°)   Wind: {wind} mph", WHITE, C))
    bullet(_c(f"Daylight: {sr} → {ss}   UV Peak: {uv}", WHITE, C))
    bullet("")
    bullet(_c(f"Door-Knock Conditions:  ", BOLD+WHITE, C) +
           _c(cv_bar, cv_color, C) + "  " + _c(f"{cv_label} ({cv_score}/10)", BOLD+cv_color, C))

    canvass_tips = {
        "GREAT": "Perfect day to be in the field. Get out early — temps are ideal.",
        "GOOD":  "Good conditions. Aim for 9–11 AM and 5–7 PM blocks.",
        "FAIR":  "Manageable, but bring water. Avoid the 12–3 PM heat block.",
        "ROUGH": "Tough conditions today. Focus on phone/Zoom outreach instead.",
    }
    bullet(_c(f"          {canvass_tips.get(cv_label,'')}", GRAY, C))

    if uv >= 8:
        bullet(_c(f"  ⚠️  High UV ({uv}) — great solar argument! 'Sun's clearly working hard today...'", YELLOW, C))

    # Pipeline snapshot
    h2("📊  PIPELINE SNAPSHOT", MAGENTA)
    won_rev   = stats.get("won_revenue", 0)
    pipe_val  = stats.get("pipeline_value", 0)
    active    = stats.get("total_active", 0)
    won_count = stats.get("won_count", 0)

    bullet(_c(f"Active Leads:  {active}", WHITE, C) + "   " +
           _c(f"Deals Won:  {won_count}  (${won_rev:,.0f})", GREEN, C))
    bullet(_c(f"Pipeline:  ${pipe_val:,.0f}  in active proposals", YELLOW, C))
    if won_rev > 0 or pipe_val > 0:
        total = won_rev + pipe_val
        bullet(_c(f"Total Revenue+Pipeline:  ${total:,.0f}", BOLD+GREEN, C))

    # ── Action items ─────────────────────────────────────────────────────────
    total_calls = result["total_calls_today"]

    h2(f"📋  TODAY'S ACTION LIST  ({total_calls} contacts)", WHITE)
    ln(_c(f"  Priority order — work top to bottom:", GRAY, C))

    call_num = 1

    def fmt_lead_line(l, label_color, action):
        addr_short = l["address"].split(",")[0]
        score_str  = _c(f"{l['score']}/100", score_color(l["score"], C), C) if l["score"] else ""
        savings_str = f"  ${l['yr1_savings']:,.0f}/yr" if l.get("yr1_savings") else ""
        note_str   = f"  · {l['last_note'][:50]}..." if l.get("last_note") and len(l.get("last_note","")) > 10 else (f"  · {l['last_note']}" if l.get("last_note") else "")
        stale_str  = _c(f"  ({l['days_stale']}d ago)", RED if l["days_stale"] > 7 else YELLOW, C) if l["days_stale"] else ""
        name_str   = f" ({l['contact_name']})" if l.get("contact_name") else ""
        phone_str  = f"  📞 {l['phone']}" if l.get("phone") else ""
        return (f"  {call_num}. {_c(action,label_color,C)}  {addr_short}{name_str}{stale_str}\n"
                f"     {score_str}{savings_str}{phone_str}\n"
                f"     {_c('Stage: '+STAGE_LABELS.get(l['stage'],l['stage']),GRAY,C)}{note_str}")

    if buckets["urgent"]:
        ln(""); ln(_c("  🔴  URGENT — New leads gone cold (5+ days, never called)", BOLD+RED, C))
        for l in buckets["urgent"][:4]:
            lines.append(fmt_lead_line(l, RED, "CALL NOW"))
            call_num += 1

    if buckets["followup"]:
        ln(""); ln(_c("  🟡  FOLLOW UP — Contacted/Qualified, stale 3+ days", BOLD+YELLOW, C))
        for l in buckets["followup"][:4]:
            lines.append(fmt_lead_line(l, YELLOW, "FOLLOW UP"))
            call_num += 1

    if buckets["nurture"]:
        ln(""); ln(_c("  🟣  NURTURE — Proposals outstanding, keep warm", BOLD+MAGENTA, C))
        for l in buckets["nurture"][:3]:
            lines.append(fmt_lead_line(l, MAGENTA, "CHECK IN"))
            call_num += 1

    if buckets["fresh"]:
        ln(""); ln(_c("  🟢  FRESH — New leads (<2 days), reach out today", BOLD+GREEN, C))
        for l in buckets["fresh"][:3]:
            lines.append(fmt_lead_line(l, GREEN, "FIRST TOUCH"))
            call_num += 1

    if not pl:
        ln(_c("  No active pipeline leads. Use batch_enrich.py or the dashboard to add leads.", GRAY, C))

    # ── Hot new prospects from cache ─────────────────────────────────────────
    if new_leads:
        h2("🔥  HOT PROSPECTS FROM ENRICHMENT CACHE", RED)
        ln(_c("  Recent high-score leads ready for outreach:", GRAY, C))
        ln()
        for i, l in enumerate(new_leads[:5], 1):
            addr_short = l["address"].split(",")[0]
            city_state = ", ".join(l["address"].split(",")[1:3]).strip() if "," in l["address"] else ""
            bar = score_bar(l["score"], width=15, use_color=C)
            savings = f"  ${l['yr1_savings']:,.0f}/yr savings" if l["yr1_savings"] else ""
            itc = f"  ${l['itc']:,.0f} ITC" if l.get("itc") else ""
            kw  = f"  {l['system_kw']:.1f}kW" if l.get("system_kw") else ""
            priority_col = GREEN if l["priority"] == "HOT" else YELLOW
            lines.append(f"  {i}. {_c(l['priority'],BOLD+priority_col,C)} {_c(addr_short,WHITE,C)}{_c(city_state,GRAY,C)}")
            lines.append(f"     {bar}{savings}{itc}{kw}")
            if l.get("talking_points"):
                tp = l["talking_points"][0]
                wrapped = textwrap.fill(tp, width=65, subsequent_indent="          ")
                lines.append(f"     {_c('→',GREEN,C)} {_c(wrapped,GRAY,C)}")
            ln()

    # ── Opening line suggestions ─────────────────────────────────────────────
    h2("💬  DOOR-KNOCK OPENERS FOR TODAY", GREEN)
    temp_hook = ""
    max_temp = weather.get("max_temp_f", temp)
    if max_temp > 100:
        temp_hook = (f"'On a scorching {max_temp}°F day like today, your AC is running at full blast — "
                     f"that's exactly where solar savings are biggest. Let me show you what it means for your bill...'")
    elif max_temp > 90:
        temp_hook = (f"'On a {max_temp}°F day like today, your AC is running hard — "
                     f"that's exactly where solar savings stack up...'")
    elif weather.get("uv_index", 0) >= 7:
        temp_hook = (f"'With UV at {weather.get('uv_index',7)} today, you can literally feel the solar energy — "
                     f"let me show you what that means for your bill...'")
    else:
        temp_hook = ("'Most homeowners in this area are saving over $150/month — "
                     "I'm going door to door today to see if your home qualifies...'")

    ln(f"  {_c('Weather hook:', BOLD+CYAN, C)}")
    ln(f"  {_c(temp_hook, WHITE, C)}")
    ln()
    ln(f"  {_c('Neighbor proof:', BOLD+CYAN, C)}")
    ln("  " + _c("'I just helped a neighbor two streets over lock in $2,100/yr in savings.", WHITE, C))
    ln("  " + _c("Their install was last month — they're thrilled. Is your home south-facing?'", WHITE, C))
    ln()
    ln(f"  {_c('ITC urgency:', BOLD+CYAN, C)}")
    itc_line1 = '"The 30% federal tax credit is still active — homeowners who install this year pocket'
    itc_line2 = ' an extra $6-8K vs waiting. That window could close with the next budget cycle."'
    ln("  " + _c(itc_line1, WHITE, C))
    ln("  " + _c(itc_line2, WHITE, C))

    # ── Footer ────────────────────────────────────────────────────────────────
    ln()
    ln(_c("═" * 70, CYAN, C))
    ln(_c(f"  Generated by Solar Intelligence Suite  ·  {date_str}  ·  {time_str}", GRAY, C))
    ln(_c(f"  http://localhost:8765  |  solar_enrich.py  |  scripts/pipeline.py", GRAY, C))
    ln(_c("═" * 70, CYAN, C))

    text = "\n".join(lines)
    result["formatted_text"] = text
    result["plain_text"] = strip_ansi(text)
    return result


def score_color(score, use_color):
    if score >= 80: return GREEN if use_color else ""
    elif score >= 60: return YELLOW if use_color else ""
    return RED if use_color else ""


# ── Save digest ───────────────────────────────────────────────────────────────
def save_briefing(text, path=None):
    if path is None:
        path = os.path.join(CACHE_DIR, "morning_briefing.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Morning Rep Briefing Generator")
    parser.add_argument("--rep",    default="Solar Rep",  help="Rep name")
    parser.add_argument("--city",   default="Phoenix,AZ", help="City for weather (e.g. 'Phoenix,AZ')")
    parser.add_argument("--json",   action="store_true",  help="Output JSON")
    parser.add_argument("--save",   action="store_true",  help="Save to cache/morning_briefing.txt")
    parser.add_argument("--output", default=None,         help="Custom output path")
    parser.add_argument("--no-color", dest="no_color", action="store_true")
    args = parser.parse_args()

    use_color = not args.no_color and sys.stdout.isatty()
    result = generate_briefing(rep_name=args.rep, city=args.city, use_color=use_color)

    if args.json:
        out = {k: v for k, v in result.items() if k not in ("formatted_text", "plain_text")}
        print(json.dumps(out, indent=2))
    else:
        print(result["formatted_text"])

    if args.save or args.output:
        saved = save_briefing(result["plain_text"], args.output)
        if not args.json:
            print(f"\n  Saved to: {saved}")
