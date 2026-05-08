#!/usr/bin/env python3
"""
Neighborhood Canvass Tool — Solar Intelligence Suite
======================================================
Given a seed address (new install, referral, or target zone center), this tool:

  1. Finds N nearby residential homes within a radius
  2. Enriches each with full Solar API data + lead scoring
  3. Builds an optimized door-knock route (greedy nearest-neighbor walk)
  4. Generates personalized door-knocker talking points for each stop
  5. Saves a printable canvass sheet + JSON data to cache/

Usage:
    python scripts/canvass_neighbors.py "1234 W Oak St, Chandler, AZ" --radius 500 --homes 10
    python scripts/canvass_neighbors.py "1234 W Oak St, Chandler, AZ" --neighbor-name "The Johnsons"
    python scripts/canvass_neighbors.py "1234 W Oak St, Chandler, AZ" --bill 200 --output canvass.txt
    python scripts/canvass_neighbors.py "1234 W Oak St, Chandler, AZ" --json

Options:
    --radius N          Search radius in meters (default: 400m ≈ 4-5 blocks)
    --homes N           Max homes to find and score (default: 10, max: 20)
    --bill N            Assumed avg monthly bill for neighbors (default: 175)
    --rate N            Utility rate $/kWh (default: 0.14)
    --neighbor-name X   Name of the signed customer for social proof messaging
    --output PATH       Save canvass sheet to this file (default: auto in cache/)
    --json              Output JSON instead of formatted report
    --no-color          Plain text output (for piping / printing)
    --hot-only          Only show HOT leads in the route
"""

import os, sys, json, math, argparse, time, hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "/root/solar-tools")

from core.solar import enrich_lead, geocode_address
from tools.territory import get_street_addresses_near
from core.config import CACHE_DIR

# ─── ANSI colors ──────────────────────────────────────────────────────────────

USE_COLOR = True

C_RESET  = "\033[0m"
C_BOLD   = "\033[1m"
C_DIM    = "\033[2m"

C_RED    = "\033[91m"
C_YELLOW = "\033[93m"
C_GREEN  = "\033[92m"
C_CYAN   = "\033[96m"
C_BLUE   = "\033[94m"
C_MAGENTA= "\033[95m"
C_WHITE  = "\033[97m"
C_GRAY   = "\033[90m"

def c(color: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"{color}{text}{C_RESET}"

def bold(text: str) -> str:
    return c(C_BOLD, text)


# ─── Score bar helper ─────────────────────────────────────────────────────────

def score_bar(score: int, width: int = 20) -> str:
    filled = int(score / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    if score >= 68:
        color = C_GREEN
    elif score >= 52:
        color = C_YELLOW
    else:
        color = C_RED
    return c(color, bar) + c(C_GRAY, f" {score}/100")


def priority_badge(priority: str, grade: str) -> str:
    badges = {
        "HOT":  (C_RED,    "🔥 HOT"),
        "WARM": (C_YELLOW, "☀️  WARM"),
        "COOL": (C_CYAN,   "❄️  COOL"),
        "LOW":  (C_GRAY,   "⬇️  LOW"),
    }
    color, label = badges.get(priority, (C_GRAY, priority))
    return c(C_BOLD, c(color, f"[{grade}] {label}"))


# ─── Walking route optimizer (greedy nearest-neighbor) ───────────────────────

def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    """Distance between two lat/lng points in meters."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def optimize_route(seed_lat: float, seed_lng: float, leads: list) -> list:
    """
    Greedy nearest-neighbor route starting from seed address.
    Prioritizes HOT leads first (within a 1.5x distance tolerance),
    then resolves remaining by proximity.
    """
    if not leads:
        return []

    # Split into HOT/WARM and COOL/LOW
    hot_warm = [l for l in leads if l.get("priority") in ("HOT", "WARM")]
    cool_low  = [l for l in leads if l.get("priority") not in ("HOT", "WARM")]

    route = []
    current_lat, current_lng = seed_lat, seed_lng

    def nearest(pool, clat, clng):
        return min(
            pool,
            key=lambda l: _haversine_m(clat, clng, l.get("lat", clat), l.get("lng", clng))
        )

    # Greedy walk through HOT/WARM first
    remaining_hw = list(hot_warm)
    while remaining_hw:
        nxt = nearest(remaining_hw, current_lat, current_lng)
        route.append(nxt)
        current_lat, current_lng = nxt.get("lat", current_lat), nxt.get("lng", current_lng)
        remaining_hw.remove(nxt)

    # Then COOL/LOW
    remaining_cl = list(cool_low)
    while remaining_cl:
        nxt = nearest(remaining_cl, current_lat, current_lng)
        route.append(nxt)
        current_lat, current_lng = nxt.get("lat", current_lat), nxt.get("lng", current_lng)
        remaining_cl.remove(nxt)

    return route


# ─── Talking point personalizer ──────────────────────────────────────────────

def door_knocker_brief(lead: dict, stop_num: int, neighbor_name: str = None, seed_address: str = None) -> list:
    """
    Generate a concise, personalized 4-line door-knocker pitch card.
    Uses neighbor social proof if available.
    """
    addr = lead.get("address", "this property")
    city = lead.get("city", "your area")
    savings = lead.get("annual_savings_yr1_usd", 0)
    monthly_savings = round(savings / 12)
    score = lead.get("lead_score", 0)
    payback = lead.get("payback_years", 0)
    system_kw = lead.get("system_size_kw", 0)
    sunshine = lead.get("sunshine_hours_per_year", 0)
    panels = lead.get("panels_recommended", 0)
    net_cost = lead.get("net_cost_usd", 0)

    lines = []

    # Opener — social proof if available
    if neighbor_name and seed_address:
        short_seed = seed_address.split(",")[0]
        lines.append(
            f"👋 \"Hi! I just helped {neighbor_name} at {short_seed} go solar — "
            f"they're saving about ${monthly_savings}/month. I wanted to see if "
            f"your home qualifies too.\""
        )
    elif seed_address:
        short_seed = seed_address.split(",")[0]
        lines.append(
            f"👋 \"Hi! I was just working with a homeowner on {short_seed} and "
            f"wanted to check a few neighbors — your roof looks like a great fit.\""
        )
    else:
        lines.append(
            f"👋 \"Hi! I'm running a solar analysis in this neighborhood — "
            f"your home came up as a top candidate.\""
        )

    # Data hook
    lines.append(
        f"📊 \"Your roof gets {sunshine:,} sunshine hours/year and fits a "
        f"{system_kw} kW system ({panels} panels).\""
    )

    # Financial hook
    lines.append(
        f"💰 \"After the 30% federal tax credit, your out-of-pocket is ~${net_cost:,.0f} — "
        f"with ~${savings:,.0f}/yr in savings and a {payback}-year payback.\""
    )

    # Close
    if score >= 82:
        lines.append(
            f"🔥 \"Honestly, this is one of the best roofs I've seen today. "
            f"5 minutes to show you the full numbers?\""
        )
    elif score >= 68:
        lines.append(
            f"☀️ \"This is a really solid setup. Can I show you a quick breakdown?\""
        )
    else:
        lines.append(
            f"📋 \"Let me pull up a quick estimate — takes less than 5 minutes.\""
        )

    return lines


# ─── Canvass runner ───────────────────────────────────────────────────────────

def run_canvass(
    seed_address: str,
    radius_m: int = 400,
    max_homes: int = 10,
    monthly_bill: float = 175.0,
    utility_rate: float = 0.14,
    neighbor_name: str = None,
    hot_only: bool = False,
) -> dict:
    """
    Full canvass pipeline: geocode → find nearby homes → enrich → route.
    """
    print(c(C_CYAN, f"\n🏘️  Solar Canvass Scanner"))
    print(c(C_GRAY, f"   Seed address: {seed_address}"))
    print(c(C_GRAY, f"   Radius: {radius_m}m  |  Max homes: {max_homes}  |  Avg bill: ${monthly_bill:.0f}/mo\n"))

    # Step 1: Geocode seed
    geo = geocode_address(seed_address)
    if "error" in geo:
        return {"error": f"Could not geocode seed address: {geo['error']}", "seed": seed_address}

    formatted_seed = geo["formatted_address"]
    seed_lat, seed_lng = geo["lat"], geo["lng"]
    print(c(C_GREEN, f"✅ Seed: {formatted_seed}"))
    print(c(C_GRAY,  f"   📍 {seed_lat:.5f}, {seed_lng:.5f}\n"))

    # Step 2: Find nearby addresses
    print(c(C_CYAN, f"🔍 Finding nearby residential addresses..."))
    addresses = get_street_addresses_near(seed_lat, seed_lng, radius_m=radius_m, max_results=max_homes + 2)

    # Exclude the seed itself
    addresses = [a for a in addresses if a != formatted_seed][:max_homes]
    print(c(C_GREEN, f"✅ Found {len(addresses)} nearby homes to analyze\n"))

    if not addresses:
        return {
            "error": "No nearby residential addresses found. Try increasing --radius.",
            "seed": formatted_seed,
            "lat": seed_lat,
            "lng": seed_lng,
        }

    # Step 3: Enrich all in parallel
    print(c(C_CYAN, f"⚡ Enriching {len(addresses)} homes with Solar API data...\n"))
    enriched = []
    errors = []

    def _enrich(addr):
        return addr, enrich_lead(addr, monthly_bill, utility_rate)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_enrich, a): a for a in addresses}
        done = 0
        for future in as_completed(futures):
            done += 1
            addr, lead = future.result()
            if "error" not in lead:
                enriched.append(lead)
                score = lead.get("lead_score", 0)
                grade = lead.get("lead_grade", "?")
                priority = lead.get("priority", "?")
                badge = priority_badge(priority, grade)
                bar = score_bar(score, 15)
                short_addr = lead["address"].split(",")[0]
                print(f"  [{done:02d}/{len(addresses)}] {badge}  {bar}  {short_addr}")
            else:
                errors.append({"address": addr, "error": lead["error"]})
                print(c(C_GRAY, f"  [{done:02d}/{len(addresses)}] ⚠️  {addr[:50]} — no data"))

    # Step 4: Filter if hot_only
    if hot_only:
        enriched = [l for l in enriched if l.get("priority") in ("HOT", "WARM")]

    # Step 5: Optimize walking route
    route = optimize_route(seed_lat, seed_lng, enriched)

    # Step 6: Stats
    hot_count  = sum(1 for l in enriched if l.get("priority") == "HOT")
    warm_count = sum(1 for l in enriched if l.get("priority") == "WARM")
    cool_count = sum(1 for l in enriched if l.get("priority") == "COOL")
    avg_score  = sum(l.get("lead_score", 0) for l in enriched) / len(enriched) if enriched else 0
    total_pipeline = sum(l.get("annual_savings_yr1_usd", 0) for l in enriched)

    # Step 7: Compute total route distance
    route_dist_m = 0
    prev_lat, prev_lng = seed_lat, seed_lng
    for lead in route:
        d = _haversine_m(prev_lat, prev_lng, lead.get("lat", prev_lat), lead.get("lng", prev_lng))
        route_dist_m += d
        prev_lat, prev_lng = lead.get("lat", prev_lat), lead.get("lng", prev_lng)
    route_dist_m += _haversine_m(prev_lat, prev_lng, seed_lat, seed_lng)  # back to start

    # Step 8: Build canvass data with door-knocker briefs
    canvass_stops = []
    for i, lead in enumerate(route, 1):
        brief = door_knocker_brief(lead, i, neighbor_name, formatted_seed)
        prev = route[i - 2] if i > 1 else None
        prev_lat2 = prev.get("lat", seed_lat) if prev else seed_lat
        prev_lng2 = prev.get("lng", seed_lng) if prev else seed_lng
        dist_from_prev = round(_haversine_m(
            prev_lat2, prev_lng2,
            lead.get("lat", prev_lat2), lead.get("lng", prev_lng2)
        ))

        canvass_stops.append({
            "stop_number": i,
            "address": lead["address"],
            "lat": lead.get("lat"),
            "lng": lead.get("lng"),
            "lead_score": lead.get("lead_score"),
            "lead_grade": lead.get("lead_grade"),
            "priority": lead.get("priority"),
            "system_size_kw": lead.get("system_size_kw"),
            "panels_recommended": lead.get("panels_recommended"),
            "annual_savings_usd": lead.get("annual_savings_yr1_usd"),
            "monthly_savings_usd": round(lead.get("annual_savings_yr1_usd", 0) / 12),
            "payback_years": lead.get("payback_years"),
            "net_cost_usd": lead.get("net_cost_usd"),
            "sunshine_hours": lead.get("sunshine_hours_per_year"),
            "dist_from_prev_m": dist_from_prev,
            "door_knocker_brief": brief,
            "score_breakdown": lead.get("score_breakdown", {}),
            "talking_points": lead.get("talking_points", []),
        })

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    seed_slug = formatted_seed.split(",")[0].replace(" ", "_").lower()[:30]
    result = {
        "canvass_id": f"canvass_{seed_slug}_{ts}",
        "generated_at": ts,
        "seed_address": formatted_seed,
        "seed_lat": seed_lat,
        "seed_lng": seed_lng,
        "neighbor_name": neighbor_name,
        "homes_analyzed": len(enriched),
        "homes_errored": len(errors),
        "hot_leads": hot_count,
        "warm_leads": warm_count,
        "cool_leads": cool_count,
        "avg_lead_score": round(avg_score, 1),
        "total_pipeline_annual_usd": round(total_pipeline),
        "route_distance_m": round(route_dist_m),
        "route_distance_blocks": round(route_dist_m / 100),
        "route_walk_minutes": round(route_dist_m / 84),  # avg ~1.4m/s walking
        "canvass_stops": canvass_stops,
        "errors": errors,
    }

    return result


# ─── Report printer ───────────────────────────────────────────────────────────

def print_report(result: dict):
    if "error" in result:
        print(c(C_RED, f"\n❌ Error: {result['error']}"))
        return

    seed = result["seed_address"]
    stops = result["canvass_stops"]
    ts = result.get("generated_at", "")

    print()
    print(c(C_BOLD, c(C_WHITE, "=" * 72)))
    print(c(C_BOLD, c(C_YELLOW, "  🏘️  SOLAR CANVASS ROUTE SHEET")))
    print(c(C_GRAY, f"  Generated: {ts}  |  Solar Intelligence Suite"))
    print(c(C_BOLD, c(C_WHITE, "=" * 72)))

    print(f"\n{bold('Seed / Social Proof Address:')}")
    print(f"  📍 {c(C_CYAN, seed)}")
    if result.get("neighbor_name"):
        print(f"  👤 Signed customer: {c(C_GREEN, result['neighbor_name'])}")

    print(f"\n{bold('Canvass Summary:')}")
    hot  = result["hot_leads"]
    warm = result["warm_leads"]
    cool = result["cool_leads"]
    total= result["homes_analyzed"]
    avg  = result["avg_lead_score"]
    dist = result["route_distance_m"]
    mins = result["route_walk_minutes"]
    pipeline = result["total_pipeline_annual_usd"]

    print(f"  Homes analyzed: {c(C_WHITE, str(total))}  |  "
          f"🔥 HOT: {c(C_RED, str(hot))}  ☀️  WARM: {c(C_YELLOW, str(warm))}  ❄️  COOL: {c(C_GRAY, str(cool))}")
    print(f"  Avg lead score: {score_bar(int(avg), 18)}")
    print(f"  Route distance: {c(C_CYAN, f'{dist:,}m')}  (~{c(C_CYAN, f'{mins} min')} walking)")
    print(f"  Pipeline value: {c(C_GREEN, f'${pipeline:,.0f}/yr')} combined potential savings")

    print(f"\n{bold('=' * 72)}")
    print(bold(c(C_CYAN, "  DOOR-KNOCK ROUTE  (optimized — HOT leads first)")))
    print(bold("=" * 72))

    for stop in stops:
        n    = stop["stop_number"]
        addr = stop["address"]
        score= stop["lead_score"]
        grade= stop["lead_grade"]
        pri  = stop["priority"]
        sav  = stop["annual_savings_usd"]
        pay  = stop["payback_years"]
        kw   = stop["system_size_kw"]
        dist_prev = stop["dist_from_prev_m"]
        brief = stop["door_knocker_brief"]

        print()
        print(c(C_BOLD, f"  STOP #{n}") + c(C_GRAY, f"  ({dist_prev}m from prev)"))
        print(f"  {c(C_WHITE, addr)}")
        print(f"  {priority_badge(pri, grade)}  {score_bar(score, 18)}")
        print(f"  💰 ${sav:,.0f}/yr savings  |  ⚡ {kw} kW  |  📅 {pay} yr payback")
        print()
        print(c(C_BOLD, c(C_CYAN, "  📋 DOOR-KNOCKER BRIEF:")))
        for line in brief:
            # Word wrap at ~65 chars
            wrapped = _wrap(line, 65)
            for wl in wrapped:
                print(f"    {wl}")
        print(c(C_GRAY, "  " + "─" * 68))

    print()
    print(c(C_BOLD, c(C_WHITE, "=" * 72)))
    print(c(C_GREEN, f"  ✅ Route complete — {total} homes  |  {hot} HOT  |  {warm} WARM"))
    if result.get("errors"):
        print(c(C_GRAY, f"  ⚠️  {len(result['errors'])} addresses had no solar data"))
    print(c(C_BOLD, c(C_WHITE, "=" * 72)))
    print()


def _wrap(text: str, width: int) -> list:
    """Simple word-wrap."""
    words = text.split()
    lines = []
    current = []
    length = 0
    for word in words:
        clean = word  # strip ANSI for length calculation (not perfect but good enough)
        if length + len(clean) + 1 > width and current:
            lines.append(" ".join(current))
            current = [word]
            length = len(clean)
        else:
            current.append(word)
            length += len(clean) + 1
    if current:
        lines.append(" ".join(current))
    return lines


# ─── Save canvass sheet ───────────────────────────────────────────────────────

def save_canvass_sheet(result: dict, output_path: str = None) -> str:
    """Save both JSON and a human-readable canvass route sheet."""
    if "error" in result:
        return None

    ts = result.get("generated_at", datetime.now().strftime("%Y%m%d_%H%M%S"))
    canvass_id = result.get("canvass_id", f"canvass_{ts}")

    # Save JSON
    json_path = os.path.join(CACHE_DIR, f"{canvass_id}.json")
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)

    # Save text route sheet
    txt_path = output_path or os.path.join(CACHE_DIR, f"{canvass_id}_route.txt")

    global USE_COLOR
    prev_color = USE_COLOR
    USE_COLOR = False  # plain text for file

    lines = []
    seed = result["seed_address"]
    stops = result["canvass_stops"]

    lines.append("=" * 72)
    lines.append("  SOLAR CANVASS ROUTE SHEET — Solar Intelligence Suite")
    lines.append(f"  Generated: {ts}")
    lines.append("=" * 72)
    lines.append(f"\nSeed address: {seed}")
    if result.get("neighbor_name"):
        lines.append(f"Signed customer: {result['neighbor_name']}")
    lines.append(f"\nHomes analyzed: {result['homes_analyzed']}")
    lines.append(f"HOT leads: {result['hot_leads']}  |  WARM: {result['warm_leads']}  |  COOL: {result['cool_leads']}")
    lines.append(f"Avg score: {result['avg_lead_score']}/100")
    lines.append(f"Route: {result['route_distance_m']}m  (~{result['route_walk_minutes']} min walk)")
    lines.append(f"Pipeline: ${result['total_pipeline_annual_usd']:,.0f}/yr combined savings")
    lines.append("\n" + "=" * 72)
    lines.append("DOOR-KNOCK ROUTE (HOT leads first)")
    lines.append("=" * 72)

    for stop in stops:
        lines.append(f"\n{'─' * 72}")
        lines.append(f"STOP #{stop['stop_number']}  [{stop['lead_grade']}] {stop['priority']}  Score: {stop['lead_score']}/100")
        lines.append(f"Address: {stop['address']}")
        lines.append(f"System: {stop['system_size_kw']} kW  |  Savings: ${stop['annual_savings_usd']:,.0f}/yr  |  Payback: {stop['payback_years']} yrs")
        lines.append(f"\nDOOR-KNOCKER BRIEF:")
        for line in stop["door_knocker_brief"]:
            for wl in _wrap(line, 70):
                lines.append(f"  {wl}")

    lines.append("\n" + "=" * 72)
    lines.append(f"END OF CANVASS ROUTE — {len(stops)} stops")
    lines.append("=" * 72)

    with open(txt_path, "w") as f:
        f.write("\n".join(lines))

    USE_COLOR = prev_color
    return txt_path, json_path


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global USE_COLOR

    parser = argparse.ArgumentParser(
        description="Solar Neighborhood Canvass Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("address", help="Seed address (new install, referral, or zone center)")
    parser.add_argument("--radius", type=int, default=400, help="Search radius in meters (default: 400)")
    parser.add_argument("--homes",  type=int, default=10,  help="Max homes to analyze (default: 10)")
    parser.add_argument("--bill",   type=float, default=175.0, help="Assumed monthly bill for neighbors (default: $175)")
    parser.add_argument("--rate",   type=float, default=0.14,  help="Utility rate $/kWh (default: 0.14)")
    parser.add_argument("--neighbor-name", type=str, default=None,
                        help="Name of signed customer for social proof talking points")
    parser.add_argument("--output", type=str, default=None, help="Path to save canvass route sheet")
    parser.add_argument("--json",    action="store_true", help="Output JSON instead of formatted report")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    parser.add_argument("--hot-only", action="store_true", help="Only include HOT/WARM leads in route")

    args = parser.parse_args()

    if args.no_color or args.json:
        USE_COLOR = False

    result = run_canvass(
        seed_address=args.address,
        radius_m=min(args.radius, 1000),  # Cap at 1km
        max_homes=min(args.homes, 20),
        monthly_bill=args.bill,
        utility_rate=args.rate,
        neighbor_name=args.neighbor_name,
        hot_only=args.hot_only,
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print_report(result)

    if "error" not in result:
        paths = save_canvass_sheet(result, args.output)
        if paths:
            txt_path, json_path = paths
            print(c(C_GRAY, f"  📁 Route sheet saved: {txt_path}"))
            print(c(C_GRAY, f"  📊 JSON data saved:   {json_path}"))
            print()


if __name__ == "__main__":
    main()
