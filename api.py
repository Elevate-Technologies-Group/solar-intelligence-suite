"""
FastAPI backend — Solar Intelligence Suite
Endpoints: lead enrichment, territory scan, proposal generation, health
Run with: uvicorn api:app --host 0.0.0.0 --port 8765 --reload
"""
import sys, os, json
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, "/root/solar-tools")

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

from core.solar import enrich_lead, geocode_address
from tools.territory import scan_territory, multi_zip_comparison

# Discord alerts (optional — skips silently if DISCORD_WEBHOOK_URL not set)
try:
    from integrations.discord_alerts import notify_hot_lead, notify_batch_results, notify_territory_scan
    _discord_enabled = True
except Exception:
    _discord_enabled = False
    def notify_hot_lead(*a, **kw): return False
    def notify_batch_results(*a, **kw): return False
    def notify_territory_scan(*a, **kw): return False

app = FastAPI(
    title="Solar Intelligence Suite",
    description="AI-powered solar lead enrichment and territory analysis for solar sales teams",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (dashboard)
static_dir = "/root/solar-tools/web/static"
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ─── models ───────────────────────────────────────────────────────────────────

class LeadRequest(BaseModel):
    address: str
    monthly_bill: float = 150.0
    utility_rate: float = 0.14

class TerritoryRequest(BaseModel):
    zip_code: str
    sample_size: int = 8
    avg_monthly_bill: float = 175.0

class MultiZipRequest(BaseModel):
    zip_codes: list[str]
    sample_size: int = 5


class BatchLeadRequest(BaseModel):
    addresses: list[str]
    monthly_bill: float = 150.0
    utility_rate: float = 0.14
    max_workers: int = 4


# ─── routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the main dashboard."""
    dash_path = "/root/solar-tools/web/dashboard.html"
    if os.path.exists(dash_path):
        with open(dash_path) as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Solar Intelligence Suite</h1><p>Dashboard loading...</p>")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Solar Intelligence Suite", "version": "1.0.0"}


@app.post("/api/lead/enrich")
async def enrich_lead_endpoint(req: LeadRequest):
    """
    Enrich a single lead address with full solar analysis.
    Returns solar potential, financials, lead score, and rep talking points.
    """
    result = enrich_lead(req.address, req.monthly_bill, req.utility_rate)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    # Discord: ping on HOT/WARM leads (fire-and-forget, non-blocking)
    try:
        if result.get("priority") in ("HOT", "WARM"):
            notify_hot_lead(result, source="api/lead/enrich")
    except Exception:
        pass
    return result


@app.get("/api/lead/enrich")
async def enrich_lead_get(
    address: str = Query(..., description="Full street address"),
    monthly_bill: float = Query(150.0, description="Monthly electric bill in USD"),
    utility_rate: float = Query(0.14, description="$/kWh utility rate")
):
    """GET version for easy browser/curl testing."""
    result = enrich_lead(address, monthly_bill, utility_rate)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.post("/api/territory/scan")
async def territory_scan(req: TerritoryRequest):
    """Scan a zip code territory and return ranked prospect list."""
    result = scan_territory(req.zip_code, req.sample_size, req.avg_monthly_bill)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    # Discord: notify on territory scan completion
    try:
        notify_territory_scan(result)
    except Exception:
        pass
    return result


@app.post("/api/territory/compare")
async def territory_compare(req: MultiZipRequest):
    """Compare multiple zip codes by solar potential and lead quality."""
    if len(req.zip_codes) > 5:
        raise HTTPException(status_code=400, detail="Max 5 zip codes per comparison")
    result = multi_zip_comparison(req.zip_codes, req.sample_size)
    return result


@app.post("/api/lead/batch")
async def batch_lead_enrich(req: BatchLeadRequest):
    """
    Enrich up to 10 addresses in parallel and return all results.

    Accepts a list of addresses with a shared monthly_bill and utility_rate.
    Results are returned sorted by lead_score (descending) so the hottest
    leads bubble to the top.

    Example request body:
        {
          "addresses": [
            "1234 W Main St, Phoenix, AZ 85001",
            "5678 N 32nd St, Scottsdale, AZ 85251"
          ],
          "monthly_bill": 195,
          "utility_rate": 0.14
        }
    """
    if not req.addresses:
        raise HTTPException(status_code=400, detail="addresses list cannot be empty")
    if len(req.addresses) > 10:
        raise HTTPException(status_code=400, detail="Max 10 addresses per batch request")

    workers = min(req.max_workers, 5)  # cap at 5 parallel workers

    results = []
    errors  = []

    def _enrich(address: str):
        return address, enrich_lead(address, req.monthly_bill, req.utility_rate)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_enrich, addr): addr for addr in req.addresses}
        for future in as_completed(futures):
            address, lead = future.result()
            if "error" in lead:
                errors.append({"address": address, "error": lead["error"]})
            else:
                results.append(lead)

    # Sort successful results by lead score descending
    results.sort(key=lambda r: r.get("lead_score", 0), reverse=True)

    hot  = sum(1 for r in results if r.get("priority") == "HOT")
    warm = sum(1 for r in results if r.get("priority") == "WARM")
    avg_score = (
        sum(r.get("lead_score", 0) for r in results) / len(results)
        if results else 0
    )

    # Discord: fire batch summary + individual HOT lead pings
    try:
        notify_batch_results(results, source_file=f"api/lead/batch ({len(req.addresses)} addrs)", hot_only=False)
    except Exception:
        pass

    return {
        "total_requested": len(req.addresses),
        "total_enriched": len(results),
        "total_errors": len(errors),
        "hot_leads": hot,
        "warm_leads": warm,
        "avg_lead_score": round(avg_score, 1),
        "results": results,
        "errors": errors,
    }


@app.get("/api/territory/cached")
async def list_cached_scans():
    """List all previously scanned territories."""
    cache_dir = "/root/solar-tools/cache"
    scans = []
    for f in os.listdir(cache_dir):
        if f.startswith("territory_") and f.endswith(".json"):
            zip_code = f.replace("territory_", "").replace(".json", "")
            fpath = os.path.join(cache_dir, f)
            with open(fpath) as fp:
                data = json.load(fp)
            scans.append({
                "zip_code": zip_code,
                "leads_enriched": data.get("leads_enriched", 0),
                "hot_leads": data.get("hot_leads", 0),
                "avg_lead_score": data.get("avg_lead_score", 0),
                "territory_grade": data.get("territory_grade", "?"),
            })
    return {"cached_scans": scans}


@app.get("/api/proposal/{address}")
async def generate_proposal(
    address: str,
    monthly_bill: float = Query(175.0),
    customer_name: str = Query("Homeowner"),
    rep_name: str = Query("Solar Advisor")
):
    """Generate a formatted proposal for a specific address."""
    lead = enrich_lead(address, monthly_bill)
    if "error" in lead:
        raise HTTPException(status_code=422, detail=lead["error"])
    
    proposal = {
        "proposal_for": customer_name,
        "prepared_by": rep_name,
        "property_address": lead["address"],
        "executive_summary": {
            "recommended_system": f"{lead['system_size_kw']} kW Solar System",
            "panels": lead["panels_recommended"],
            "annual_production_kwh": lead["annual_kwh_produced"],
            "energy_offset_pct": lead["offset_pct"],
        },
        "investment": {
            "gross_cost": f"${lead['gross_cost_usd']:,.0f}",
            "federal_tax_credit_30pct": f"${lead['federal_itc_usd']:,.0f}",
            "net_investment": f"${lead['net_cost_usd']:,.0f}",
            "monthly_loan_estimate_20yr": f"${lead['net_cost_usd'] / 240:,.0f}",
        },
        "savings": {
            "year_1_savings": f"${lead['annual_savings_yr1_usd']:,.0f}",
            "payback_period": f"{lead['payback_years']} years",
            "25_year_lifetime_savings": f"${lead['lifetime_savings_usd']:,.0f}",
            "25_year_roi": f"{lead['roi_25yr_pct']}%",
        },
        "environmental_impact": {
            "co2_offset_lbs_annually": f"{lead['co2_offset_lbs_per_year']:,.0f} lbs",
            "equivalent_trees_planted": f"{lead['trees_equivalent_per_year']} trees/year",
        },
        "roof_analysis": {
            "sunshine_hours_per_year": lead["sunshine_hours_per_year"],
            "roof_segments_analyzed": lead["roof_segments"],
            "imagery_quality": lead["imagery_quality"],
            "data_source": "Google Solar API",
        },
        "rep_talking_points": lead["talking_points"],
        "lead_intelligence": {
            "lead_grade": lead["lead_grade"],
            "priority": lead["priority"],
            "lead_score": f"{lead['lead_score']}/100",
        }
    }
    return proposal


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)
