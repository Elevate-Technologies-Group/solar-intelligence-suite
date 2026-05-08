"""
Solar API wrapper — geocoding, building insights, financial projections.
All results cached to disk so re-runs don't burn API quota.
"""
import os, json, hashlib, time, math, requests
from typing import Optional

# ─── Supabase sync ────────────────────────────────────────────────────────────
# Reads SUPABASE_URL and SUPABASE_KEY from environment.
# Gracefully skips (no-op) if either is not set.

_SUPABASE_URL = None
_SUPABASE_KEY = None
_SUPABASE_AVAILABLE = None  # None = not yet checked


def _supabase_available() -> bool:
    """Check once whether Supabase credentials are configured."""
    global _SUPABASE_AVAILABLE, _SUPABASE_URL, _SUPABASE_KEY
    if _SUPABASE_AVAILABLE is None:
        _SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
        _SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
        _SUPABASE_AVAILABLE = bool(_SUPABASE_URL and _SUPABASE_KEY)
    return _SUPABASE_AVAILABLE


def _parse_imagery_date(d) -> str:
    """Convert imagery_date dict to ISO string."""
    if isinstance(d, dict):
        y = d.get("year")
        m = d.get("month", 1)
        return f"{y}-{m:02d}-01" if y else None
    return str(d) if d else None


def sync_lead_to_supabase(lead: dict, raw_address: str = None) -> dict:
    """
    Upsert an enriched lead record to Supabase (solar_leads table).

    - Reads SUPABASE_URL and SUPABASE_KEY from env.
    - Gracefully skips (returns {\"skipped\": True}) if creds not set.
    - Uses the formatted_address as the natural upsert key.
    - Returns the Supabase response dict or skip/error info.

    Requires the solar_leads table from integrations/supabase_schema.py.
    """
    if not _supabase_available():
        return {"skipped": True, "reason": "SUPABASE_URL or SUPABASE_KEY not set in environment"}

    if not lead or "error" in lead:
        return {"skipped": True, "reason": "Lead has errors — not synced"}

    # Build the record to upsert
    record = {
        "raw_address": raw_address or lead.get("address", ""),
        "formatted_address": lead.get("address"),
        "lat": lead.get("lat"),
        "lng": lead.get("lng"),
        "city": lead.get("city"),
        "state": lead.get("state"),
        "postal_code": lead.get("postal_code"),

        # Solar potential
        "sunshine_hours_per_year": lead.get("sunshine_hours_per_year"),
        "roof_segments": lead.get("roof_segments"),
        "max_panels_possible": lead.get("max_panels_possible"),
        "panels_recommended": lead.get("panels_recommended"),
        "system_size_kw": lead.get("system_size_kw"),
        "annual_kwh_produced": lead.get("annual_kwh_produced"),
        "annual_kwh_needed": lead.get("annual_kwh_needed"),
        "energy_offset_pct": lead.get("offset_pct"),
        "imagery_quality": lead.get("imagery_quality"),

        # Financials
        "monthly_bill_usd": lead.get("monthly_bill_usd"),
        "gross_cost_usd": lead.get("gross_cost_usd"),
        "federal_itc_usd": lead.get("federal_itc_usd"),
        "net_cost_usd": lead.get("net_cost_usd"),
        "annual_savings_yr1_usd": lead.get("annual_savings_yr1_usd"),
        "lifetime_savings_usd": lead.get("lifetime_savings_usd"),
        "payback_years": lead.get("payback_years"),
        "roi_25yr_pct": lead.get("roi_25yr_pct"),
        "co2_offset_lbs_per_year": lead.get("co2_offset_lbs_per_year"),

        # Lead scoring
        "lead_score": lead.get("lead_score"),
        "lead_grade": lead.get("lead_grade"),
        "priority": lead.get("priority"),
        "score_breakdown": json.dumps(lead.get("score_breakdown", {})),

        # Talking points & raw data
        "talking_points": json.dumps(lead.get("talking_points", [])),
    }

    # Remove None values (let Supabase use column defaults)
    record = {k: v for k, v in record.items() if v is not None}

    headers = {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates",
    }

    url = f"{_SUPABASE_URL}/rest/v1/solar_leads"

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=record,
            timeout=15,
            params={"on_conflict": "formatted_address"},  # upsert on address
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            lead_id = data[0].get("id") if isinstance(data, list) and data else None
            return {"synced": True, "id": lead_id, "status_code": resp.status_code}
        else:
            return {
                "synced": False,
                "status_code": resp.status_code,
                "error": resp.text[:500],
            }
    except Exception as e:
        return {"synced": False, "error": str(e)}
from core.config import (
    GOOGLE_MAPS_API_KEY, SOLAR_BASE, MAPS_BASE, CACHE_DIR,
    DEFAULT_PANEL_COST_USD, DEFAULT_UTILITY_RATE_KWH,
    DEFAULT_FEDERAL_ITC, DEFAULT_PANEL_CAPACITY_W
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _cache_path(key: str) -> str:
    h = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.json")


def _cached(key: str):
    p = _cache_path(key)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


def _save(key: str, data: dict):
    with open(_cache_path(key), "w") as f:
        json.dump(data, f, indent=2)


def _get(url: str, params: dict) -> dict:
    """GET with retry and caching."""
    cache_key = url + json.dumps(params, sort_keys=True)
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            _save(cache_key, data)
            return data
        except Exception as e:
            if attempt == 2:
                return {"error": str(e)}
            time.sleep(2 ** attempt)


# ─── geocoding ────────────────────────────────────────────────────────────────

def geocode_address(address: str) -> dict:
    """Convert address to lat/lng + formatted address."""
    data = _get(f"{MAPS_BASE}/geocode/json", {
        "address": address,
        "key": GOOGLE_MAPS_API_KEY
    })
    if data.get("status") != "OK":
        return {"error": data.get("status", "Unknown error"), "address": address}
    result = data["results"][0]
    loc = result["geometry"]["location"]
    return {
        "formatted_address": result["formatted_address"],
        "lat": loc["lat"],
        "lng": loc["lng"],
        "place_id": result.get("place_id"),
        "postal_code": next(
            (c["long_name"] for c in result.get("address_components", [])
             if "postal_code" in c["types"]), None
        ),
        "city": next(
            (c["long_name"] for c in result.get("address_components", [])
             if "locality" in c["types"]), None
        ),
        "state": next(
            (c["short_name"] for c in result.get("address_components", [])
             if "administrative_area_level_1" in c["types"]), None
        ),
    }


# ─── solar building insights ─────────────────────────────────────────────────

def get_building_insights(lat: float, lng: float, quality: str = "HIGH") -> dict:
    """Pull raw Solar API building insights."""
    data = _get(f"{SOLAR_BASE}/buildingInsights:findClosest", {
        "location.latitude": lat,
        "location.longitude": lng,
        "requiredQuality": quality,
        "key": GOOGLE_MAPS_API_KEY
    })
    if "error" in data:
        # Fallback to LOW quality
        if quality != "LOW":
            return get_building_insights(lat, lng, "LOW")
    return data


# ─── financial calculations ───────────────────────────────────────────────────

def calculate_financials(
    annual_kwh: float,
    num_panels: int,
    panel_capacity_w: float = DEFAULT_PANEL_CAPACITY_W,
    utility_rate: float = DEFAULT_UTILITY_RATE_KWH,
    cost_per_watt: float = DEFAULT_PANEL_COST_USD,
    itc_rate: float = DEFAULT_FEDERAL_ITC,
    annual_rate_increase: float = 0.03,
    system_lifetime_years: int = 25,
) -> dict:
    system_kw = (num_panels * panel_capacity_w) / 1000
    gross_cost = system_kw * 1000 * cost_per_watt
    itc_savings = gross_cost * itc_rate
    net_cost = gross_cost - itc_savings

    # Annual savings (compounding utility rate increases)
    annual_savings_yr1 = annual_kwh * utility_rate
    lifetime_savings = sum(
        annual_kwh * utility_rate * ((1 + annual_rate_increase) ** y)
        for y in range(system_lifetime_years)
    )

    payback_years = net_cost / annual_savings_yr1 if annual_savings_yr1 > 0 else 0
    roi_pct = ((lifetime_savings - net_cost) / net_cost * 100) if net_cost > 0 else 0

    return {
        "system_size_kw": round(system_kw, 2),
        "gross_cost_usd": round(gross_cost, 0),
        "federal_itc_usd": round(itc_savings, 0),
        "net_cost_usd": round(net_cost, 0),
        "annual_savings_yr1_usd": round(annual_savings_yr1, 0),
        "lifetime_savings_usd": round(lifetime_savings, 0),
        "payback_years": round(payback_years, 1),
        "roi_25yr_pct": round(roi_pct, 1),
        "co2_offset_lbs_per_year": round(annual_kwh * 0.85, 0),  # avg US grid
        "trees_equivalent_per_year": round(annual_kwh * 0.85 / 48, 1),
    }


# ─── lead enrichment (full pipeline) ─────────────────────────────────────────

def enrich_lead(address: str, monthly_bill: float = 150.0, utility_rate: float = DEFAULT_UTILITY_RATE_KWH) -> dict:
    """
    Full lead enrichment pipeline:
    address → geocode → solar insights → financial projections → lead score
    Returns a structured profile ready for GHL or rep script injection.
    """
    # Step 1: Geocode
    geo = geocode_address(address)
    if "error" in geo:
        return {"error": f"Geocoding failed: {geo['error']}", "address": address}

    # Step 2: Solar insights
    insights = get_building_insights(geo["lat"], geo["lng"])
    if "error" in insights:
        return {"error": f"Solar API failed: {insights['error']}", "geo": geo}

    sp = insights.get("solarPotential", {})
    if not sp:
        return {"error": "No solar potential data returned", "geo": geo}

    # Step 3: Pick optimal panel config based on monthly bill
    estimated_monthly_kwh = monthly_bill / utility_rate
    annual_kwh_needed = estimated_monthly_kwh * 12
    panel_capacity_w = sp.get("panelCapacityWatts", DEFAULT_PANEL_CAPACITY_W)

    # Find best config that covers their usage
    configs = sp.get("solarPanelConfigs", [])
    best_config = None
    if configs:
        # Find smallest config that meets their annual need
        for cfg in configs:
            if cfg.get("yearlyEnergyDcKwh", 0) >= annual_kwh_needed:
                best_config = cfg
                break
        if not best_config:
            best_config = configs[-1]  # Max available
    
    panels_recommended = best_config.get("panelsCount", sp.get("maxArrayPanelsCount", 20)) if best_config else sp.get("maxArrayPanelsCount", 20)
    annual_kwh_produced = best_config.get("yearlyEnergyDcKwh", sp.get("maxArrayAnnualEnergyKwh", 0)) if best_config else sp.get("maxArrayAnnualEnergyKwh", 0)

    # If no annual kwh data (common with LOW quality), estimate from panel count
    if annual_kwh_produced == 0:
        sunshine_hrs = sp.get("maxSunshineHoursPerYear", 1600)
        annual_kwh_produced = panels_recommended * panel_capacity_w / 1000 * sunshine_hrs * 0.8  # 80% efficiency

    # Step 4: Financial projections
    fin = calculate_financials(
        annual_kwh=annual_kwh_produced,
        num_panels=panels_recommended,
        panel_capacity_w=panel_capacity_w,
        utility_rate=utility_rate,
    )

    # Step 5: Lead scoring (0-100)
    score = _score_lead(sp, fin, monthly_bill)

    roof_segments = sp.get("roofSegmentStats", [])
    best_segment = max(roof_segments, key=lambda s: s.get("stats", {}).get("sunshineQuantiles", [0])[-1], default={}) if roof_segments else {}

    return {
        "address": geo["formatted_address"],
        "lat": geo["lat"],
        "lng": geo["lng"],
        "city": geo["city"],
        "state": geo["state"],
        "postal_code": geo["postal_code"],

        # Solar data
        "sunshine_hours_per_year": round(sp.get("maxSunshineHoursPerYear", 0)),
        "roof_segments": len(roof_segments),
        "max_panels_possible": sp.get("maxArrayPanelsCount", 0),
        "panels_recommended": panels_recommended,
        "system_size_kw": fin["system_size_kw"],
        "annual_kwh_produced": round(annual_kwh_produced),
        "annual_kwh_needed": round(annual_kwh_needed),
        "offset_pct": round(annual_kwh_produced / annual_kwh_needed * 100) if annual_kwh_needed > 0 else 0,
        "imagery_date": insights.get("imageryDate", {}),
        "imagery_quality": insights.get("imageryProcessingState", "UNKNOWN"),

        # Financials
        **fin,

        # Lead intelligence
        "monthly_bill_usd": monthly_bill,
        "lead_score": score["total"],
        "score_breakdown": score["breakdown"],
        "lead_grade": score["grade"],
        "priority": score["priority"],

        # Rep talking points (pre-built)
        "talking_points": _build_talking_points(geo, sp, fin, score, monthly_bill),
    }


def _score_lead(sp: dict, fin: dict, monthly_bill: float) -> dict:
    """Score a lead 0-100 based on solar potential and financial fit."""
    breakdown = {}

    # Sunshine hours (max 25 pts)
    sunshine = sp.get("maxSunshineHoursPerYear", 0)
    sun_score = min(25, int(sunshine / 80))
    breakdown["sunshine"] = sun_score

    # Roof segments / complexity (max 15 pts)
    segments = len(sp.get("roofSegmentStats", []))
    seg_score = 15 if segments >= 3 else (10 if segments == 2 else 5)
    breakdown["roof_quality"] = seg_score

    # Monthly bill (max 30 pts — higher bill = better prospect)
    if monthly_bill >= 300: bill_score = 30
    elif monthly_bill >= 200: bill_score = 25
    elif monthly_bill >= 150: bill_score = 20
    elif monthly_bill >= 100: bill_score = 12
    else: bill_score = 5
    breakdown["monthly_bill"] = bill_score

    # Payback period (max 20 pts)
    payback = fin.get("payback_years", 99)
    if payback <= 6: pay_score = 20
    elif payback <= 8: pay_score = 16
    elif payback <= 10: pay_score = 12
    elif payback <= 12: pay_score = 8
    else: pay_score = 3
    breakdown["payback"] = pay_score

    # ROI (max 10 pts)
    roi = fin.get("roi_25yr_pct", 0)
    roi_score = min(10, int(roi / 30))
    breakdown["roi"] = roi_score

    total = sum(breakdown.values())
    if total >= 80: grade, priority = "A+", "HOT"
    elif total >= 65: grade, priority = "A", "HOT"
    elif total >= 50: grade, priority = "B", "WARM"
    elif total >= 35: grade, priority = "C", "COOL"
    else: grade, priority = "D", "LOW"

    return {"total": total, "breakdown": breakdown, "grade": grade, "priority": priority}


def _build_talking_points(geo: dict, sp: dict, fin: dict, score: dict, monthly_bill: float) -> list:
    """Generate rep-ready talking points for this specific address."""
    pts = []
    city = geo.get("city", "your area")
    sunshine = sp.get("maxSunshineHoursPerYear", 0)
    panels = fin.get("system_size_kw", 0)

    pts.append(f"✅ Your roof gets {sunshine:,} hours of sunshine per year — that's {'above' if sunshine > 1600 else 'solid'} average for {city}.")
    pts.append(f"💰 Based on your ~${monthly_bill:.0f}/month electric bill, you'd save roughly ${fin.get('annual_savings_yr1_usd', 0):,.0f} in year one alone.")
    pts.append(f"⚡ A {fin.get('system_size_kw', 0)} kW system would produce enough to cover your usage — and potentially bank credits.")
    pts.append(f"🏛️ The 30% federal tax credit means your out-of-pocket drops from ${fin.get('gross_cost_usd', 0):,.0f} to just ${fin.get('net_cost_usd', 0):,.0f}.")
    pts.append(f"📅 At that rate, you break even in about {fin.get('payback_years', 0)} years — then it's free power for the next {25 - int(fin.get('payback_years', 0))}+.")
    pts.append(f"🌱 You'd offset {fin.get('co2_offset_lbs_per_year', 0):,.0f} lbs of CO₂ per year — like planting {int(fin.get('trees_equivalent_per_year', 0))} trees.")
    pts.append(f"📈 Over 25 years, total lifetime savings: ${fin.get('lifetime_savings_usd', 0):,.0f}.")

    return pts
