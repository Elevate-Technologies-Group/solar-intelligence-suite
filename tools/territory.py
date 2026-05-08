"""
Territory Scanner — geocode a zip code, find residential addresses,
enrich each one with Solar API data, and rank by lead score.
Designed to give reps pre-scored prospect lists before they dial.
"""
import os, json, time, requests
from typing import Optional
from core.config import GOOGLE_MAPS_API_KEY, PLACES_BASE, MAPS_BASE, CACHE_DIR
from core.solar import enrich_lead


# ─── zip → neighborhoods → addresses ─────────────────────────────────────────

def zip_to_center(zip_code: str) -> Optional[dict]:
    """Get center lat/lng of a zip code."""
    import sys
    sys.path.insert(0, "/root/solar-tools")
    from core.solar import geocode_address
    return geocode_address(zip_code)


def search_residential_areas(lat: float, lng: float, radius_m: int = 2000) -> list:
    """
    Use Places API to find residential neighborhoods / street intersections
    around a center point. Returns a grid of sample points to probe.
    """
    # Build a grid of sample points within the radius
    points = []
    step = radius_m / 111000  # degrees per meter (approx)
    
    for dlat in [-0.5, 0, 0.5]:
        for dlng in [-0.5, 0, 0.5]:
            if dlat == 0 and dlng == 0:
                points.append((lat, lng))
            else:
                points.append((lat + dlat * step * 2, lng + dlng * step * 2))
    
    return points


def get_street_addresses_near(lat: float, lng: float, radius_m: int = 500, max_results: int = 10) -> list:
    """
    Use Geocoding API reverse-geocode a grid of points to get real addresses.
    Much cheaper than Places nearby search.
    """
    addresses = []
    seen = set()
    
    # Sample a grid of points around the center
    offsets = [
        (0, 0), (0.002, 0), (-0.002, 0), (0, 0.003), (0, -0.003),
        (0.002, 0.003), (-0.002, 0.003), (0.002, -0.003), (-0.002, -0.003),
        (0.001, 0.002), (-0.001, -0.002)
    ]
    
    for dlat, dlng in offsets:
        if len(addresses) >= max_results:
            break
        
        r = requests.get(
            f"{MAPS_BASE}/geocode/json",
            params={
                "latlng": f"{lat + dlat},{lng + dlng}",
                "result_type": "street_address",
                "key": GOOGLE_MAPS_API_KEY
            },
            timeout=10
        )
        
        if r.status_code != 200:
            continue
        
        data = r.json()
        if data.get("status") == "OK":
            for result in data.get("results", [])[:2]:
                addr = result.get("formatted_address", "")
                if addr and addr not in seen:
                    seen.add(addr)
                    # Filter to likely residential (not business)
                    types = result.get("types", [])
                    if "street_address" in types or "premise" in types:
                        addresses.append(addr)
        
        time.sleep(0.1)  # rate limiting
    
    return addresses[:max_results]


def scan_territory(
    zip_code: str,
    sample_size: int = 8,
    avg_monthly_bill: float = 175.0,
    save_results: bool = True
) -> dict:
    """
    Full territory scan:
    1. Find center of zip code
    2. Sample residential addresses
    3. Enrich each with Solar API
    4. Rank by lead score
    5. Return prioritized prospect list
    """
    print(f"🔍 Scanning territory: {zip_code}")
    
    geo = zip_to_center(zip_code)
    if "error" in geo:
        return {"error": f"Could not locate zip code {zip_code}"}
    
    print(f"📍 Center: {geo['formatted_address']} ({geo['lat']:.4f}, {geo['lng']:.4f})")
    
    # Get sample addresses
    addresses = get_street_addresses_near(geo["lat"], geo["lng"], max_results=sample_size)
    print(f"🏠 Found {len(addresses)} residential addresses to analyze")
    
    # Enrich each lead
    results = []
    for i, addr in enumerate(addresses):
        print(f"  ⚡ [{i+1}/{len(addresses)}] {addr}")
        lead = enrich_lead(addr, monthly_bill=avg_monthly_bill)
        if "error" not in lead:
            results.append(lead)
        time.sleep(0.2)
    
    # Sort by lead score
    results.sort(key=lambda x: x.get("lead_score", 0), reverse=True)
    
    # Summary stats
    if results:
        avg_score = sum(r.get("lead_score", 0) for r in results) / len(results)
        hot_leads = [r for r in results if r.get("priority") == "HOT"]
        avg_savings = sum(r.get("annual_savings_yr1_usd", 0) for r in results) / len(results)
        avg_payback = sum(r.get("payback_years", 0) for r in results) / len(results)
    else:
        avg_score = avg_savings = avg_payback = 0
        hot_leads = []
    
    scan_result = {
        "zip_code": zip_code,
        "center": geo["formatted_address"],
        "lat": geo["lat"],
        "lng": geo["lng"],
        "addresses_scanned": len(addresses),
        "leads_enriched": len(results),
        "hot_leads": len(hot_leads),
        "avg_lead_score": round(avg_score, 1),
        "avg_annual_savings_usd": round(avg_savings),
        "avg_payback_years": round(avg_payback, 1),
        "territory_grade": "HOT" if avg_score >= 65 else ("WARM" if avg_score >= 45 else "COOL"),
        "prospects": results,
    }
    
    if save_results:
        out_path = os.path.join(CACHE_DIR, f"territory_{zip_code}.json")
        with open(out_path, "w") as f:
            json.dump(scan_result, f, indent=2)
        print(f"💾 Results saved: {out_path}")
        scan_result["saved_to"] = out_path
    
    return scan_result


def multi_zip_comparison(zip_codes: list, sample_size: int = 5) -> dict:
    """Scan multiple zip codes and rank territories by solar potential."""
    results = []
    for zip_code in zip_codes:
        print(f"\n{'='*50}")
        scan = scan_territory(zip_code, sample_size=sample_size)
        if "error" not in scan:
            results.append({
                "zip_code": zip_code,
                "grade": scan["territory_grade"],
                "avg_score": scan["avg_lead_score"],
                "hot_leads": scan["hot_leads"],
                "avg_savings_yr1": scan["avg_annual_savings_usd"],
                "avg_payback_yrs": scan["avg_payback_years"],
            })
    
    results.sort(key=lambda x: x["avg_score"], reverse=True)
    return {
        "territories_scanned": len(zip_codes),
        "rankings": results,
        "best_territory": results[0] if results else None
    }
