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

# Canvass tool import (optional — graceful if missing)
try:
    from scripts.canvass_neighbors import run_canvass
    _canvass_enabled = True
except Exception:
    _canvass_enabled = False

# Follow-up sequence generator import (optional — graceful if missing)
try:
    from scripts.generate_followup import generate_sequence as _gen_followup_seq, save_txt as _save_followup_txt
    _followup_enabled = True
except Exception:
    _followup_enabled = False

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


class CanvassRequest(BaseModel):
    seed_address: str
    radius_m: int = 400
    max_homes: int = 10
    monthly_bill: float = 175.0
    utility_rate: float = 0.14
    neighbor_name: Optional[str] = None
    hot_only: bool = False


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


@app.get("/api/stats")
async def get_stats():
    """Aggregate stats across all cached territory data and enriched leads."""
    import glob
    cache_dir = "/root/solar-tools/cache"
    all_leads = []
    territories = []

    for f in os.listdir(cache_dir):
        if f.startswith("territory_") and f.endswith(".json") and "compare" not in f:
            fpath = os.path.join(cache_dir, f)
            try:
                with open(fpath) as fp:
                    data = json.load(fp)
                territories.append(data)
                prospects = data.get("prospects", [])
                for p in prospects:
                    p["_zip"] = data.get("zip_code", "")
                    p["_city"] = data.get("city", "")
                all_leads.extend(prospects)
            except Exception:
                pass

    # Deduplicate by address
    seen = set()
    unique_leads = []
    for lead in all_leads:
        key = lead.get("address", "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique_leads.append(lead)

    total = len(unique_leads)
    hot = sum(1 for l in unique_leads if l.get("priority") == "HOT")
    warm = sum(1 for l in unique_leads if l.get("priority") == "WARM")
    cool = sum(1 for l in unique_leads if l.get("priority") == "COOL")
    low = sum(1 for l in unique_leads if l.get("priority") == "LOW")
    avg_score = round(sum(l.get("lead_score", 0) for l in unique_leads) / max(1, total), 1)
    total_pipeline = round(sum(l.get("annual_savings_yr1_usd", 0) for l in unique_leads))
    avg_savings = round(total_pipeline / max(1, total))
    avg_payback = round(sum(l.get("payback_years", 0) for l in unique_leads) / max(1, total), 1)

    territory_list = []
    for t in territories:
        territory_list.append({
            "zip_code": t.get("zip_code"),
            "territory_grade": t.get("territory_grade", "?"),
            "avg_lead_score": t.get("avg_lead_score", 0),
            "hot_leads": t.get("hot_leads", 0),
            "leads_enriched": t.get("leads_enriched", 0),
            "avg_annual_savings_usd": t.get("avg_annual_savings_usd", 0),
        })
    territory_list.sort(key=lambda x: x["avg_lead_score"], reverse=True)

    top_leads = sorted(unique_leads, key=lambda x: x.get("lead_score", 0), reverse=True)[:5]
    top_leads_clean = [{
        "address": l.get("address", ""),
        "lead_score": l.get("lead_score", 0),
        "lead_grade": l.get("lead_grade", "?"),
        "priority": l.get("priority", "?"),
        "annual_savings_yr1_usd": l.get("annual_savings_yr1_usd", 0),
        "payback_years": l.get("payback_years", 0),
        "panels_recommended": l.get("panels_recommended", 0),
        "sunshine_hours_per_year": l.get("sunshine_hours_per_year", 0),
    } for l in top_leads]

    return {
        "total_leads": total,
        "hot_leads": hot,
        "warm_leads": warm,
        "cool_leads": cool,
        "low_leads": low,
        "avg_lead_score": avg_score,
        "total_pipeline_yr1_usd": total_pipeline,
        "avg_annual_savings_usd": avg_savings,
        "avg_payback_years": avg_payback,
        "territories_scanned": len(territories),
        "territories": territory_list,
        "top_leads": top_leads_clean,
    }


@app.get("/api/leads/history")
async def get_leads_history(
    priority: str = Query("", description="Filter by HOT/WARM/COOL/LOW"),
    zip_code: str = Query("", description="Filter by zip code"),
    min_score: int = Query(0, description="Minimum lead score"),
    limit: int = Query(50, description="Max results"),
    sort_by: str = Query("lead_score", description="Sort field"),
):
    """Return all enriched leads from cache, optionally filtered."""
    cache_dir = "/root/solar-tools/cache"
    all_leads = []

    for f in os.listdir(cache_dir):
        if f.startswith("territory_") and f.endswith(".json") and "compare" not in f:
            fpath = os.path.join(cache_dir, f)
            try:
                with open(fpath) as fp:
                    data = json.load(fp)
                zip_val = data.get("zip_code", "")
                city_val = data.get("city", "")
                for p in data.get("prospects", []):
                    p["_zip"] = zip_val
                    p["_city"] = city_val
                    all_leads.append(p)
            except Exception:
                pass

    # Also check canvass files
    for f in os.listdir(cache_dir):
        if f.startswith("canvass_") and f.endswith(".json"):
            fpath = os.path.join(cache_dir, f)
            try:
                with open(fpath) as fp:
                    data = json.load(fp)
                for stop in data.get("canvass_stops", []):
                    lead = stop.get("lead", {})
                    if lead and "lead_score" in lead:
                        lead["_zip"] = lead.get("postal_code", "")
                        lead["_city"] = lead.get("city", "")
                        all_leads.append(lead)
            except Exception:
                pass

    # Deduplicate
    seen = set()
    unique = []
    for lead in all_leads:
        key = lead.get("address", lead.get("formatted_address", "")).lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(lead)

    # Filter
    if priority:
        unique = [l for l in unique if l.get("priority", "").upper() == priority.upper()]
    if zip_code:
        unique = [l for l in unique if l.get("_zip", "") == zip_code or l.get("postal_code", "") == zip_code]
    if min_score > 0:
        unique = [l for l in unique if l.get("lead_score", 0) >= min_score]

    # Sort
    reverse = True
    if sort_by == "payback_years":
        reverse = False
    unique.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse)

    # Clean for response
    results = []
    for l in unique[:limit]:
        results.append({
            "address": l.get("address", l.get("formatted_address", "")),
            "city": l.get("city", l.get("_city", "")),
            "state": l.get("state", ""),
            "zip_code": l.get("postal_code", l.get("_zip", "")),
            "lead_score": l.get("lead_score", 0),
            "lead_grade": l.get("lead_grade", "?"),
            "priority": l.get("priority", "?"),
            "annual_savings_yr1_usd": l.get("annual_savings_yr1_usd", 0),
            "lifetime_savings_usd": l.get("lifetime_savings_usd", 0),
            "payback_years": l.get("payback_years", 0),
            "panels_recommended": l.get("panels_recommended", 0),
            "system_size_kw": l.get("system_size_kw", 0),
            "sunshine_hours_per_year": l.get("sunshine_hours_per_year", 0),
            "roof_segments": l.get("roof_segments", 0),
            "imagery_date": l.get("imagery_date", ""),
            "net_cost_usd": l.get("net_cost_usd", 0),
            "roi_25yr_pct": l.get("roi_25yr_pct", 0),
        })

    return {
        "total": len(results),
        "leads": results,
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


@app.post("/api/lead/canvass")
async def canvass_neighborhood(req: CanvassRequest):
    """
    Neighborhood canvass tool — find and score homes near a seed address.

    Given a seed address (a new solar install, referral, or target zone),
    this endpoint:
      1. Finds up to `max_homes` nearby residential addresses within `radius_m`
      2. Enriches each with full Solar API data + lead scoring
      3. Builds an optimized door-knock route (HOT leads first, greedy walk)
      4. Generates personalized door-knocker talking points for each stop
      5. Returns the full canvass route sorted for maximum conversion

    The `neighbor_name` field enables social proof messaging in talking points:
    "Hi! I just helped [neighbor_name] go solar — they're saving $X/month..."

    Example request:
        {
          "seed_address": "1234 W Oak St, Chandler, AZ 85224",
          "radius_m": 400,
          "max_homes": 8,
          "monthly_bill": 195,
          "neighbor_name": "The Garcias"
        }
    """
    if not _canvass_enabled:
        raise HTTPException(
            status_code=503,
            detail="Canvass module not available. Check scripts/canvass_neighbors.py."
        )

    result = run_canvass(
        seed_address=req.seed_address,
        radius_m=min(req.radius_m, 1000),
        max_homes=min(req.max_homes, 20),
        monthly_bill=req.monthly_bill,
        utility_rate=req.utility_rate,
        neighbor_name=req.neighbor_name,
        hot_only=req.hot_only,
    )

    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])

    return result



# ─── Proposal generator import (optional) ─────────────────────────────────────
try:
    from scripts.generate_proposal import render_proposal as _render_proposal
    _proposal_enabled = True
except Exception as _e:
    _proposal_enabled = False


class ProposalRequest(BaseModel):
    address: str
    monthly_bill: float = 150.0
    utility_rate: float = 0.14
    homeowner_name: str = ""
    rep_name: str = ""
    company_name: str = "Elevate Solar"
    save_file: bool = True


@app.post("/api/lead/proposal")
async def generate_proposal(req: ProposalRequest):
    """
    Generate a standalone HTML solar proposal for a homeowner.

    Enriches the address with full solar analysis, then renders a
    beautiful, branded HTML one-pager the rep can email or text to
    the prospect directly from the field.

    Returns:
      - html_proposal: the full HTML string (inline, no external deps)
      - file_path: path where the file was saved on the server (if save_file=True)
      - lead: the enriched lead data used to build the proposal
      - summary: key figures for quick reference

    Example:
        POST /api/lead/proposal
        {
          "address": "1905 E Marquette Dr, Gilbert AZ 85234",
          "monthly_bill": 195,
          "homeowner_name": "The Garcia Family",
          "rep_name": "Jake Torres"
        }
    """
    if not _proposal_enabled:
        raise HTTPException(status_code=503, detail="Proposal module unavailable. Check scripts/generate_proposal.py.")

    lead = enrich_lead(req.address, req.monthly_bill, req.utility_rate)
    if "error" in lead:
        raise HTTPException(status_code=422, detail=lead["error"])

    html = _render_proposal(
        lead,
        homeowner_name=req.homeowner_name,
        rep_name=req.rep_name,
        company_name=req.company_name,
    )

    file_path = None
    if req.save_file:
        import re
        from pathlib import Path
        from datetime import datetime
        proposals_dir = Path("/root/solar-tools/cache/proposals")
        proposals_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r'[^a-z0-9]+', '_', lead['address'].lower())[:60]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = proposals_dir / f"proposal_{slug}_{ts}.html"
        out_path.write_text(html, encoding="utf-8")
        file_path = str(out_path)

    return {
        "html_proposal": html,
        "file_path": file_path,
        "lead": lead,
        "summary": {
            "address": lead["address"],
            "lead_score": lead["lead_score"],
            "priority": lead["priority"],
            "grade": lead["lead_grade"],
            "annual_savings_usd": lead["annual_savings_yr1_usd"],
            "lifetime_savings_usd": lead["lifetime_savings_usd"],
            "payback_years": lead["payback_years"],
            "system_size_kw": lead["system_size_kw"],
            "panels": lead["panels_recommended"],
            "net_cost_usd": lead["net_cost_usd"],
            "federal_itc_usd": lead["federal_itc_usd"],
        }
    }


@app.get("/api/lead/proposal")
async def generate_proposal_get(
    address: str = Query(..., description="Full street address"),
    monthly_bill: float = Query(150.0, description="Monthly electric bill"),
    utility_rate: float = Query(0.14, description="$/kWh"),
    homeowner_name: str = Query("", description="Homeowner name for proposal header"),
    rep_name: str = Query("", description="Rep name"),
    company_name: str = Query("Elevate Solar", description="Company name"),
):
    """GET version — returns HTML directly (open in browser to preview)."""
    if not _proposal_enabled:
        raise HTTPException(status_code=503, detail="Proposal module unavailable.")

    lead = enrich_lead(address, monthly_bill, utility_rate)
    if "error" in lead:
        raise HTTPException(status_code=422, detail=lead["error"])

    html = _render_proposal(lead, homeowner_name=homeowner_name, rep_name=rep_name, company_name=company_name)

    # Save file
    import re
    from pathlib import Path
    from datetime import datetime
    proposals_dir = Path("/root/solar-tools/cache/proposals")
    proposals_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r'[^a-z0-9]+', '_', lead['address'].lower())[:60]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = proposals_dir / f"proposal_{slug}_{ts}.html"
    out_path.write_text(html, encoding="utf-8")

    return HTMLResponse(html)


class FollowupRequest(BaseModel):
    address: str
    monthly_bill: float = 175.0
    utility_rate: float = 0.14
    homeowner_name: str = ""
    rep_name: str = ""
    rep_phone: str = ""
    company_name: str = "Elevate Solar"
    save_txt: bool = False


@app.post("/api/lead/followup")
async def generate_followup_sequence(req: FollowupRequest):
    """
    Generate a personalized 5-touch SMS + email follow-up sequence for a solar lead.

    Enriches the address, then builds a 14-day drip sequence with real data
    (savings, system size, payback, ITC savings) embedded in every message.

    Returns:
      - touches: list of 5 touch objects (day, channel, subject, body, notes, cta)
      - summary: lead snapshot + rep info
      - lead: full enriched lead data

    Example:
        POST /api/lead/followup
        {
          "address": "1905 E Marquette Dr, Gilbert AZ 85234",
          "monthly_bill": 195,
          "homeowner_name": "The Garcia Family",
          "rep_name": "Jake Torres",
          "rep_phone": "602-555-0192"
        }
    """
    if not _followup_enabled:
        raise HTTPException(status_code=503, detail="Follow-up module unavailable. Check scripts/generate_followup.py.")

    lead = enrich_lead(req.address, req.monthly_bill, req.utility_rate)
    if "error" in lead:
        raise HTTPException(status_code=422, detail=lead["error"])

    seq = _gen_followup_seq(
        lead,
        homeowner_name=req.homeowner_name,
        rep_name=req.rep_name,
        rep_phone=req.rep_phone,
        company_name=req.company_name,
    )

    file_path = None
    if req.save_txt:
        try:
            file_path = _save_followup_txt(seq)
        except Exception as e:
            file_path = f"error: {e}"

    return {
        "touches": seq["touches"],
        "summary": seq["summary"],
        "lead": seq["lead"],
        "file_path": file_path,
    }


@app.get("/api/lead/followup")
async def generate_followup_get(
    address: str = Query(..., description="Full street address"),
    monthly_bill: float = Query(175.0, description="Monthly electric bill"),
    utility_rate: float = Query(0.14, description="$/kWh"),
    homeowner_name: str = Query("", description="Homeowner name"),
    rep_name: str = Query("", description="Rep name"),
    rep_phone: str = Query("", description="Rep phone"),
    company_name: str = Query("Elevate Solar", description="Company name"),
    save_txt: bool = Query(False, description="Save plain-text copy to cache/followup/"),
):
    """GET version of follow-up sequence generator (query params)."""
    if not _followup_enabled:
        raise HTTPException(status_code=503, detail="Follow-up module unavailable.")

    lead = enrich_lead(address, monthly_bill, utility_rate)
    if "error" in lead:
        raise HTTPException(status_code=422, detail=lead["error"])

    seq = _gen_followup_seq(
        lead,
        homeowner_name=homeowner_name,
        rep_name=rep_name,
        rep_phone=rep_phone,
        company_name=company_name,
    )

    file_path = None
    if save_txt:
        try:
            file_path = _save_followup_txt(seq)
        except Exception as e:
            file_path = f"error: {e}"

    return {
        "touches": seq["touches"],
        "summary": seq["summary"],
        "lead": seq["lead"],
        "file_path": file_path,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)