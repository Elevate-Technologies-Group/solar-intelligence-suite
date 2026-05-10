"""
FastAPI backend — Solar Intelligence Suite
Endpoints: lead enrichment, territory scan, proposal generation, health
Run with: uvicorn api:app --host 0.0.0.0 --port 8765 --reload
"""
import sys, os, json
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, "/root/solar-tools")

from fastapi import FastAPI, HTTPException, Query, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

from core.solar import enrich_lead, geocode_address
from core.config import DEFAULT_UTILITY_RATE_KWH
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

# Territory report generator import (optional — graceful if missing)
try:
    from scripts.generate_territory_report import (
        get_territory_data as _get_territory_data,
        generate_territory_report_html as _gen_territory_html,
        save_report as _save_territory_report,
    )
    _territory_report_enabled = True
except Exception as _e:
    _territory_report_enabled = False

try:
    from integrations.discord_alerts import notify_hot_lead, notify_batch_results, notify_territory_scan
    _discord_enabled = True
except Exception:
    _discord_enabled = False
    def notify_hot_lead(*a, **kw): return False
    def notify_batch_results(*a, **kw): return False
    def notify_territory_scan(*a, **kw): return False

# Lead map generator import (optional — graceful if missing)
try:
    from scripts.build_lead_map import (
        collect_all_leads as _collect_map_leads,
        leads_to_geojson  as _leads_to_geojson,
        generate_map_html as _gen_map_html,
        save_map          as _save_map,
    )
    _lead_map_enabled = True
except Exception:
    _lead_map_enabled = False

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


@app.get("/api/territory/report", response_class=HTMLResponse)
async def territory_report_html(
    zip_code: str = Query(..., description="ZIP code to generate report for"),
    monthly_bill: float = Query(175.0, description="Assumed monthly electric bill"),
    company: str = Query("Elevate Solar", description="Company name on report"),
    live: bool = Query(False, description="Force fresh scan (ignore cache)"),
    download: bool = Query(False, description="Return as file download attachment"),
):
    """
    Generate a standalone HTML Territory Intelligence Report for any ZIP code.
    Reads cached territory data or runs a live scan.
    Returns a beautiful, printable HTML page — open directly in browser.

    Example: GET /api/territory/report?zip_code=85234
    """
    if not _territory_report_enabled:
        raise HTTPException(status_code=503, detail="Territory report module unavailable.")

    try:
        data = _get_territory_data(zip_code, live=live, monthly_bill=monthly_bill)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load territory data: {e}")

    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"No data for ZIP {zip_code}. Use ?live=true to trigger a fresh scan."
        )

    html = _gen_territory_html(data, zip_code, generated_by=company)

    # Save a copy to cache
    try:
        saved_path = _save_territory_report(html, zip_code)
    except Exception:
        saved_path = None

    if download:
        from fastapi.responses import Response
        return Response(
            content=html,
            media_type="text/html",
            headers={"Content-Disposition": f"attachment; filename=territory_{zip_code}.html"},
        )

    return HTMLResponse(content=html)


@app.get("/api/territory/report/json")
async def territory_report_json(
    zip_code: str = Query(..., description="ZIP code"),
    monthly_bill: float = Query(175.0, description="Assumed monthly electric bill"),
    live: bool = Query(False, description="Force fresh scan"),
):
    """
    Return territory data as JSON (same data that powers the HTML report).
    Useful for building custom dashboards or exporting to GHL/CRMs.
    """
    if not _territory_report_enabled:
        raise HTTPException(status_code=503, detail="Territory report module unavailable.")

    try:
        data = _get_territory_data(zip_code, live=live, monthly_bill=monthly_bill)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load territory data: {e}")

    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"No data for ZIP {zip_code}. Use ?live=true to trigger a fresh scan."
        )

    prospects = data.get("prospects", [])
    return {
        "zip_code": zip_code,
        "center": data.get("center", ""),
        "territory_grade": data.get("territory_grade", "UNKNOWN"),
        "avg_lead_score": data.get("avg_lead_score", 0),
        "total_leads": len(prospects),
        "hot_leads": data.get("hot_leads", 0),
        "warm_leads": sum(1 for p in prospects if p.get("priority") == "WARM"),
        "avg_annual_savings_usd": data.get("avg_annual_savings_usd", 0),
        "avg_payback_years": data.get("avg_payback_years", 0),
        "total_pipeline_yr1_usd": sum(
            p.get("annual_savings_yr1_usd", 0) for p in prospects if p.get("priority") in ("HOT","WARM")
        ),
        "prospects": prospects,
        "report_url": f"/api/territory/report?zip_code={zip_code}",
    }


@app.get("/api/leads/map", response_class=HTMLResponse)
async def leads_map_html(
    title: str = Query("Solar Lead Map", description="Map page title"),
    download: bool = Query(False, description="Return as file download"),
):
    """
    Interactive HTML map of all cached solar leads — color-coded pins.
    Red=HOT, Orange=WARM, Blue=COOL. Click any pin for full lead details.
    Example: GET /api/leads/map
    """
    if not _lead_map_enabled:
        raise HTTPException(status_code=503, detail="Lead map module unavailable.")

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    leads   = _collect_map_leads()
    geojson = _leads_to_geojson(leads)
    html    = _gen_map_html(geojson, google_maps_key=api_key, title=title)
    try:
        _save_map(html)
    except Exception:
        pass

    if download:
        from fastapi.responses import Response
        return Response(content=html, media_type="text/html",
                        headers={"Content-Disposition": "attachment; filename=solar_lead_map.html"})
    return HTMLResponse(content=html)


@app.get("/api/leads/map/data")
async def leads_map_geojson():
    """
    All cached leads as GeoJSON FeatureCollection — for custom map integrations.
    """
    if not _lead_map_enabled:
        raise HTTPException(status_code=503, detail="Lead map module unavailable.")
    leads   = _collect_map_leads()
    geojson = _leads_to_geojson(leads)
    features = geojson.get("features", [])
    return {
        "type":       "FeatureCollection",
        "total":      len(features),
        "hot_leads":  sum(1 for f in features if f["properties"]["priority"] == "HOT"),
        "warm_leads": sum(1 for f in features if f["properties"]["priority"] == "WARM"),
        "features":   features,
    }


# ── Cost of Waiting API ───────────────────────────────────────────────────────
try:
    from scripts.cost_of_waiting import calculate_waiting_cost as _calc_waiting
    _waiting_enabled = True
except Exception:
    _waiting_enabled = False

class WaitingCostRequest(BaseModel):
    address:     Optional[str]   = None
    monthly_bill: float          = 175.0
    utility_rate: float          = 0.14
    months:       int            = 24
    escalation:   float          = 0.035
    enrich:       bool           = True

@app.post("/api/lead/waiting-cost",
    summary="Cost of Waiting Calculator",
    tags=["Lead Intelligence"])
async def lead_waiting_cost(req: WaitingCostRequest):
    """
    Calculate the financial cost of delaying solar adoption.
    Returns per-month breakdown, bill escalation projections, and closing talking points.

    If `address` is provided and `enrich=true`, runs full Solar API enrichment first.
    Otherwise uses bill-only estimates.
    """
    if not _waiting_enabled:
        raise HTTPException(status_code=503, detail="Cost of waiting module unavailable.")

    lead = {}
    if req.address and req.enrich:
        try:
            lead = enrich_lead(req.address, req.monthly_bill, req.utility_rate)
        except Exception as e:
            lead = {}

    waiting = _calc_waiting(
        monthly_bill            = req.monthly_bill,
        annual_savings_yr1      = lead.get("annual_savings_yr1_usd"),
        net_system_cost         = lead.get("net_cost_usd"),
        payback_years           = lead.get("payback_years"),
        months_to_evaluate      = min(req.months, 36),
        utility_rate_escalation = req.escalation,
        system_size_kw          = lead.get("system_size_kw"),
        panels                  = lead.get("panels_recommended"),
    )

    return {
        "address":      req.address,
        "lead":         lead,
        "waiting_cost": waiting,
    }


@app.get("/api/lead/waiting-cost",
    summary="Cost of Waiting (quick GET)",
    tags=["Lead Intelligence"])
async def lead_waiting_cost_get(
    address:      Optional[str] = Query(None),
    monthly_bill: float         = Query(175.0),
    utility_rate: float         = Query(0.14),
    months:       int           = Query(24),
):
    """Quick GET version — no request body needed. Enrich by default if address given."""
    if not _waiting_enabled:
        raise HTTPException(status_code=503, detail="Cost of waiting module unavailable.")

    lead = {}
    if address:
        try:
            lead = enrich_lead(address, monthly_bill, utility_rate)
        except Exception:
            lead = {}

    waiting = _calc_waiting(
        monthly_bill            = monthly_bill,
        annual_savings_yr1      = lead.get("annual_savings_yr1_usd"),
        net_system_cost         = lead.get("net_cost_usd"),
        payback_years           = lead.get("payback_years"),
        months_to_evaluate      = min(months, 36),
        system_size_kw          = lead.get("system_size_kw"),
        panels                  = lead.get("panels_recommended"),
    )

    return {
        "address":      address,
        "lead":         lead,
        "waiting_cost": waiting,
    }


@app.get("/api/lead/waiting-cost/widget",
    response_class=HTMLResponse,
    summary="Embeddable Cost of Waiting widget (HTML)",
    tags=["Lead Intelligence"])
async def waiting_cost_widget(
    bill:         float         = Query(175.0, description="Monthly electric bill"),
    address:      Optional[str] = Query(None, description="Pre-fill address"),
    primary_color:str           = Query("f97316", description="Brand color hex (no #)"),
    company:      str           = Query("Elevate Solar", description="Company name"),
    phone:        str           = Query("", description="Company phone"),
):
    """
    Returns a fully standalone embeddable HTML widget showing Cost of Waiting.
    Embed on any website with: <iframe src='/api/lead/waiting-cost/widget?bill=175' ...>
    Or serve directly as a landing page / popup.
    """
    widget_html = _build_waiting_widget(
        monthly_bill  = bill,
        address       = address or "",
        primary_color = primary_color,
        company_name  = company,
        company_phone = phone,
    )
    return HTMLResponse(content=widget_html)


def _build_waiting_widget(
    monthly_bill: float,
    address: str = "",
    primary_color: str = "f97316",
    company_name: str = "Elevate Solar",
    company_phone: str = "",
) -> str:
    """Build a standalone embeddable HTML Cost of Waiting widget."""
    pc = primary_color.lstrip("#")

    address_val = address.replace('"', '&quot;')

    if company_phone:
        cta_button = "<a href='tel:" + company_phone + "' class='cta-btn'>Call " + company_phone + " Now</a>"
    else:
        cta_button = "<button class='cta-btn' onclick=\"alert('Contact " + company_name + " to get started!')\">Get My Free Quote &rarr;</button>"

    bill_val = f"{monthly_bill:.0f}"

    # Build HTML using string concatenation (no f-string backslash issues)
    parts = []
    parts.append("<!DOCTYPE html>\n<html lang='en'>\n<head>\n")
    parts.append("<meta charset='UTF-8'>\n")
    parts.append("<meta name='viewport' content='width=device-width, initial-scale=1.0'>\n")
    parts.append(f"<title>Cost of Waiting &mdash; {company_name}</title>\n")
    parts.append("""<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  .widget { max-width: 680px; margin: 0 auto; padding: 24px 16px; }
  .hero { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
          border: 1px solid #334155; border-radius: 16px; padding: 28px 24px 20px;
          text-align: center; margin-bottom: 20px; }
  .hero-sun { font-size: 2.4rem; margin-bottom: 8px; }
  .hero h1 { font-size: 1.5rem; font-weight: 800; color: #fff; margin-bottom: 4px; }
  .hero p  { color: #94a3b8; font-size: 0.9rem; }
  .calc-card { background: #1e293b; border: 1px solid #334155; border-radius: 12px;
               padding: 20px; margin-bottom: 16px; }
  .calc-card h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.1em;
                  color: #64748b; margin-bottom: 14px; }
  .input-row { display: flex; gap: 12px; flex-wrap: wrap; }
  .input-group { flex: 1; min-width: 180px; }
  .input-group label { display: block; font-size: 0.78rem; color: #94a3b8; margin-bottom: 5px; }
  .input-group input { width: 100%; background: #0f172a; border: 1px solid #334155;
                       color: #e2e8f0; padding: 9px 12px; border-radius: 8px; font-size: 0.95rem; }
  .calc-btn { width: 100%; margin-top: 14px; padding: 12px; color: #fff;
              border: none; border-radius: 10px; font-size: 1rem;
              font-weight: 700; cursor: pointer; transition: opacity 0.15s; }
  .calc-btn:hover { opacity: 0.85; }
  .calc-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .cost-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;
               margin-bottom: 16px; }
  .cost-card { background: #1e293b; border: 1px solid #334155; border-radius: 12px;
               padding: 16px; text-align: center; }
  .cost-card .label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em;
                      color: #64748b; margin-bottom: 4px; }
  .cost-card .amount { font-size: 1.6rem; font-weight: 800; }
  .cost-card .amount.danger  { color: #ef4444; }
  .cost-card .amount.warning { color: #f97316; }
  .cost-card .sub { font-size: 0.72rem; color: #64748b; margin-top: 3px; }
  .table-card { background: #1e293b; border: 1px solid #334155; border-radius: 12px;
                padding: 18px; margin-bottom: 16px; }
  .table-card h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.1em;
                   color: #64748b; margin-bottom: 12px; }
  .esc-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  .esc-table th { color: #64748b; font-size: 0.72rem; text-transform: uppercase;
                  letter-spacing: 0.06em; padding: 4px 8px; text-align: right; border-bottom: 1px solid #334155; }
  .esc-table th:first-child { text-align: left; }
  .esc-table td { padding: 7px 8px; text-align: right; border-bottom: 1px solid #1e293b; }
  .esc-table td:first-child { text-align: left; color: #94a3b8; }
  .esc-table tr.hl td { color: #ef4444; font-weight: 700; }
  .esc-table tr:last-child td { border-bottom: none; }
  .points-card { background: #1e293b; border: 1px solid #334155; border-radius: 12px;
                 padding: 18px; margin-bottom: 16px; }
  .points-card h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.1em;
                    color: #64748b; margin-bottom: 12px; }
  .point { display: flex; gap: 10px; margin-bottom: 10px; align-items: flex-start; }
  .point-icon { font-size: 1rem; flex-shrink: 0; }
  .point-text { font-size: 0.85rem; color: #cbd5e1; line-height: 1.5; }
  .cta { border-radius: 12px; padding: 20px; text-align: center; margin-bottom: 16px; }
  .cta h3 { font-size: 1rem; font-weight: 700; color: #fff; margin-bottom: 6px; }
  .cta p  { font-size: 0.82rem; color: #94a3b8; margin-bottom: 14px; }
  .cta-btn { display: inline-block; color: #fff; padding: 12px 28px;
             border-radius: 8px; font-weight: 700; font-size: 0.95rem; text-decoration: none;
             cursor: pointer; border: none; }
  .loading { text-align: center; padding: 16px; color: #64748b; font-size: 0.85rem; display: none; }
  .footer { text-align: center; font-size: 0.72rem; color: #475569; padding-top: 8px; }
  .hidden { display: none !important; }
  .fadeIn { animation: fadeIn 0.3s ease; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
</style>\n""")
    parts.append("</head>\n<body>\n<div class='widget'>\n")
    parts.append(f"""
  <div class='hero'>
    <div class='hero-sun'>&#9728;&#65039;</div>
    <h1>What Does <span style='color:#{pc}'>Waiting</span> Cost You?</h1>
    <p>Every month without solar is money you'll never get back. See your real numbers.</p>
  </div>
  <div class='calc-card'>
    <h2>&#9889; Your Numbers</h2>
    <div class='input-row'>
      <div class='input-group'>
        <label>Monthly Electric Bill ($)</label>
        <input type='number' id='bill' value='{bill_val}' min='50' max='1000' step='5'
               style='background:#0f172a;border:1px solid #334155;color:#e2e8f0;'>
      </div>
      <div class='input-group'>
        <label>Your Address (optional)</label>
        <input type='text' id='address' placeholder='123 Main St, Phoenix AZ' value='{address_val}'
               style='background:#0f172a;border:1px solid #334155;color:#e2e8f0;'>
      </div>
    </div>
    <button class='calc-btn' id='calcBtn' onclick='runCalc()'
            style='background:#{pc}'>Calculate My Cost of Waiting &rarr;</button>
  </div>
  <div class='loading' id='loading'>&#9203; Analyzing your home's solar potential...</div>
  <div id='results' class='hidden'>
    <div class='cost-grid fadeIn' id='costGrid'></div>
    <div class='table-card fadeIn'>
      <h2>&#128200; Your Electric Bill Without Solar</h2>
      <table class='esc-table'>
        <thead><tr><th>Year</th><th>Monthly</th><th>Annual</th><th>Extra Cost</th></tr></thead>
        <tbody id='escBody'></tbody>
      </table>
      <p style='font-size:0.72rem;color:#475569;margin-top:8px;'>
        Based on 3.5% average annual utility rate escalation (EIA national average)
      </p>
    </div>
    <div class='points-card fadeIn'>
      <h2>&#128161; Your Solar Opportunity</h2>
      <div id='pointsList'></div>
    </div>
    <div class='cta fadeIn' style='background:linear-gradient(135deg,#{pc}22,#{pc}11);border:1px solid #{pc}44;'>
      <h3>Don't Give the Utility More Money &mdash; Go Solar Today</h3>
      <p>Lock in your savings before rates climb further. Free analysis, no commitment.</p>
      <span style='display:inline-block;background:#{pc};border-radius:8px;padding:2px 0;'>{cta_button}</span>
    </div>
  </div>
  <div class='footer'>Powered by {company_name} Solar Intelligence Suite &bull;
    Estimates based on Google Solar API + EIA utility data</div>
</div>
""")

    # JavaScript (no f-string needed — static JS)
    parts.append("""<script>
async function runCalc() {
  const bill    = parseFloat(document.getElementById('bill').value) || 175;
  const address = document.getElementById('address').value.trim();
  const btn     = document.getElementById('calcBtn');
  const loading = document.getElementById('loading');
  btn.disabled = true; btn.textContent = 'Calculating...';
  loading.style.display = 'block';
  document.getElementById('results').classList.add('hidden');
  try {
    let data;
    if (address) {
      const params = new URLSearchParams({ address, monthly_bill: bill });
      const resp = await fetch('/api/lead/waiting-cost?' + params);
      data = await resp.json();
    } else { data = buildBillOnly(bill); }
    renderResults(data, bill);
    document.getElementById('results').classList.remove('hidden');
    document.getElementById('results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch(e) {
    const data = buildBillOnly(bill);
    renderResults(data, bill);
    document.getElementById('results').classList.remove('hidden');
  } finally {
    btn.disabled = false; btn.textContent = 'Recalculate';
    loading.style.display = 'none';
  }
}

function buildBillOnly(bill) {
  const esc = 0.035, syr = bill * 12 * 0.72, smo = syr / 12;
  const kw = Math.max(4, (bill / 175) * 7.5), nc = kw * 3000 * 0.70, itc = kw * 3000 * 0.30;
  const bd = [], opts = [3, 6, 12, 18, 24];
  for (const m of opts) {
    let elec = 0, lost = 0;
    for (let i = 1; i <= m; i++) {
      elec += bill * Math.pow(1 + esc, i/12);
      if (i > 2) lost += smo * Math.pow(1 + esc, (i-2)/12);
    }
    bd.push({ months: m, electricity_paid_usd: elec, lost_solar_savings_usd: lost, total_cost_of_waiting_usd: elec + lost });
  }
  const t12 = bd.find(d => d.months === 12) || bd[bd.length - 1];
  return { waiting_cost: { monthly_bill: bill, annual_savings_yr1_usd: syr, net_system_cost_usd: nc,
    payback_years: nc / syr, monthly_savings_usd: smo, itc_amount_usd: itc, itc_pct: 0.30,
    utility_rate_escalation: esc, twelve_month_summary: t12, monthly_breakdown: bd,
    talking_points: [
      'Every month you wait costs $' + Math.round(smo) + ' in savings you never get back.',
      'Over 12 months, you will pay $' + Math.round(bill * 12) + ' to the utility that solar would eliminate.',
      'Waiting 12 months costs $' + Math.round(t12.total_cost_of_waiting_usd) + ' total.',
      'At 3.5%/yr escalation, your bill grows to $' + Math.round(bill * 1.035) + '/mo next year.',
      'The 30% federal ITC saves you $' + Math.round(itc) + ' — that incentive exists now.',
      'Your system pays back in ' + (nc / syr).toFixed(1) + ' years, then 15+ years of free power.',
    ] }, lead: {} };
}

function fmt(n) { return '$' + Math.round(n).toLocaleString(); }

function renderResults(data, bill) {
  const w = data.waiting_cost, bd = w.monthly_breakdown || [], twl = w.twelve_month_summary || {};
  const m3 = bd.find(d => d.months === 3) || {}, m6 = bd.find(d => d.months === 6) || {};
  const m24 = bd.find(d => d.months === 24) || {};
  document.getElementById('costGrid').innerHTML =
    card('Cost of Waiting 3 Mo', m3.total_cost_of_waiting_usd, m3.electricity_paid_usd, m3.lost_solar_savings_usd, 'warning') +
    card('Cost of Waiting 6 Mo', m6.total_cost_of_waiting_usd, m6.electricity_paid_usd, m6.lost_solar_savings_usd, 'warning') +
    card('&#9888; 12 Months Cost', twl.total_cost_of_waiting_usd, twl.electricity_paid_usd, twl.lost_solar_savings_usd, 'danger') +
    card('Cost of Waiting 24 Mo', m24.total_cost_of_waiting_usd, m24.electricity_paid_usd, m24.lost_solar_savings_usd, 'danger');
  const esc = w.utility_rate_escalation || 0.035;
  const yrs = [['Now',0],['Year 1',1],['Year 2',2],['Year 5',5],['Year 10',10],['Year 20',20]];
  document.getElementById('escBody').innerHTML = yrs.map(([yr, n]) => {
    const mo = bill * Math.pow(1+esc, n), ann = mo * 12, extra = mo - bill;
    const hl = (n >= 10) ? " class='hl'" : '';
    return "<tr" + hl + "><td>" + yr + "</td><td>" + fmt(mo) + "/mo</td><td>" + fmt(ann) + "/yr</td><td>+" + fmt(extra) + "</td></tr>";
  }).join('');
  const icons = ['&#128184;','&#128202;','&#9889;','&#128200;','&#127963;','&#128262;','&#127919;'];
  document.getElementById('pointsList').innerHTML = (w.talking_points || []).map((pt, i) =>
    "<div class='point'><span class='point-icon'>" + icons[i % icons.length] + "</span>" +
    "<span class='point-text'>" + pt + "</span></div>"
  ).join('');
}

function card(label, total, elec, lost, cls) {
  return "<div class='cost-card'>" +
    "<div class='label'>" + label + "</div>" +
    "<div class='amount " + cls + "'>" + fmt(total || 0) + "</div>" +
    "<div class='sub'>" + fmt(elec || 0) + " bills + " + fmt(lost || 0) + " lost savings</div>" +
    "</div>";
}

window.addEventListener('DOMContentLoaded', () => {
  const bill = parseFloat(document.getElementById('bill').value);
  if (bill > 0 && !document.getElementById('address').value) {
    const data = buildBillOnly(bill);
    renderResults(data, bill);
    document.getElementById('results').classList.remove('hidden');
  }
});
</script>
</body>
</html>""")

    return "".join(parts)


# ── Financing Calculator ──────────────────────────────────────────────────────

@app.post("/api/lead/financing",
    summary="Solar financing calculator — $0-down monthly payment vs current bill",
    tags=["Lead Intelligence"])
async def lead_financing_post(body: dict = Body(...)):
    """
    Calculate solar financing options for an address or bill-only estimate.

    Body:
        address (str, optional): Street address to enrich with real solar data.
        monthly_bill (float): Monthly electric bill in dollars. Default: 175.
        utility_rate (float): $/kWh. Default: 0.145.
        state_credit_pct (float): Additional state tax credit %. Default: 0.0.
        enrich (bool): Whether to call Google Solar API. Default: True.

    Returns:
        Full financing breakdown: loan options, day-1 cash flow, escalation table,
        talking points, and lead data if enriched.
    """
    try:
        from scripts.financing_calculator import calculate_financing
    except ImportError as e:
        raise HTTPException(503, f"Financing module not available: {e}")

    address     = body.get("address", "")
    monthly_bill = float(body.get("monthly_bill", 175))
    utility_rate = float(body.get("utility_rate", 0.145))
    state_credit = float(body.get("state_credit_pct", 0.0))
    do_enrich    = body.get("enrich", True)

    lead = None
    if address and do_enrich:
        try:
            lead = enrich_lead(address)
        except Exception as e:
            lead = {"error": str(e)}

    result = calculate_financing(
        lead,
        monthly_bill     = monthly_bill,
        utility_rate     = utility_rate,
        include_state_incentive = state_credit,
    )
    return JSONResponse(result)


@app.get("/api/lead/financing",
    summary="Solar financing calculator (GET, bill-only or with address)",
    tags=["Lead Intelligence"])
async def lead_financing_get(
    monthly_bill: float         = Query(175.0, description="Monthly electric bill ($)"),
    address:      Optional[str] = Query(None,  description="Address for real solar data"),
    utility_rate: float         = Query(0.145, description="$/kWh"),
    state_credit: float         = Query(0.0,   description="State credit % (0.0–1.0)"),
    enrich:       bool          = Query(True,  description="Use Google Solar API"),
):
    """GET version of financing calculator — quick bill estimate or full enrichment."""
    try:
        from scripts.financing_calculator import calculate_financing
    except ImportError as e:
        raise HTTPException(503, f"Financing module not available: {e}")

    lead = None
    if address and enrich:
        try:
            lead = enrich_lead(address)
        except Exception as e:
            lead = {"error": str(e)}

    result = calculate_financing(
        lead,
        monthly_bill     = monthly_bill,
        utility_rate     = utility_rate,
        include_state_incentive = state_credit,
    )
    return JSONResponse(result)


@app.get("/api/lead/financing/widget",
    response_class=HTMLResponse,
    summary="Embeddable financing widget (HTML) — shareable with homeowners",
    tags=["Lead Intelligence"])
async def financing_widget(
    bill:          float = Query(175.0, description="Monthly electric bill"),
    address:       Optional[str] = Query(None, description="Pre-fill address"),
    primary_color: str  = Query("22c55e", description="Brand color hex (no #)"),
    company:       str  = Query("Elevate Solar", description="Company name"),
    phone:         str  = Query("", description="Company phone"),
):
    """
    Returns a standalone embeddable HTML widget for the financing calculator.
    Embed on any website:
        <iframe src='/api/lead/financing/widget?bill=175&company=Elevate+Solar' ...>
    """
    from scripts.financing_calculator import calculate_financing
    # Bill-only base for widget default state
    base = calculate_financing(None, monthly_bill=bill)
    rec  = base["recommended_option"]
    col  = f"#{primary_color}"

    widget = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Solar Financing — {company}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0f172a;color:#e2e8f0;padding:16px;min-height:100vh}}
.header{{text-align:center;padding:18px 0 14px;border-bottom:1px solid #1e293b;margin-bottom:18px}}
.header h1{{font-size:1.3rem;color:{col};font-weight:800}}
.header p{{font-size:0.8rem;color:#94a3b8;margin-top:4px}}
.input-row{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}}
.input-group{{flex:1;min-width:130px}}
.input-group label{{display:block;font-size:0.72rem;color:#94a3b8;margin-bottom:4px}}
.input-group input{{width:100%;background:#1e293b;border:1px solid #334155;
  color:#e2e8f0;padding:8px 10px;border-radius:8px;font-size:0.85rem}}
.btn{{width:100%;padding:11px;background:{col};color:#0f172a;border:none;
  border-radius:8px;font-weight:800;cursor:pointer;font-size:0.9rem;margin-bottom:14px}}
.btn:hover{{opacity:0.9}}
.summary{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}}
.stat-box{{background:#1e293b;border-radius:10px;padding:12px;text-align:center}}
.stat-val{{font-size:1.4rem;font-weight:800;color:{col}}}
.stat-lbl{{font-size:0.68rem;color:#94a3b8;margin-top:3px}}
.table-wrap{{overflow-x:auto;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;font-size:0.78rem}}
th{{background:#1e293b;padding:8px 10px;text-align:left;color:#94a3b8;
   border-bottom:1px solid #334155}}
td{{padding:8px 10px;border-bottom:1px solid #1e293b}}
tr.best td{{background:#052e16;color:{col}}}
tr.best td:first-child::before{{content:"★ ";color:{col}}}
.cf-pos{{color:#22c55e;font-weight:700}}
.cf-neg{{color:#f97316}}
.cta{{background:#1e293b;border:2px solid {col};border-radius:10px;padding:14px;
     text-align:center;margin-top:14px}}
.cta .cta-head{{font-weight:800;color:{col};font-size:0.9rem;margin-bottom:6px}}
.cta .cta-phone{{font-size:1.1rem;font-weight:800;color:#e2e8f0}}
.cta .cta-sub{{font-size:0.72rem;color:#94a3b8;margin-top:4px}}
.mode-badge{{text-align:center;font-size:0.7rem;color:#475569;margin-top:10px}}
</style>
</head>
<body>
<div class="header">
  <h1>⚡ Solar Financing Calculator</h1>
  <p>See your $0-down monthly payment vs your current bill</p>
</div>

<div class="input-row">
  <div class="input-group">
    <label>Monthly Bill ($)</label>
    <input id="w-bill" type="number" value="{bill}" min="50" max="2000" oninput="recalc()">
  </div>
  <div class="input-group" style="flex:2;min-width:180px;">
    <label>Address (for real solar data)</label>
    <input id="w-addr" type="text" placeholder="123 Main St, Phoenix AZ"
           value="{address or ''}" style="font-size:0.78rem;">
  </div>
</div>
<button class="btn" onclick="fetchCalc()">⚡ Calculate My Solar Payment</button>

<div id="w-summary" class="summary">
  <div class="stat-box">
    <div class="stat-val" id="w-pmt">${rec["monthly_payment_usd"]:.0f}/mo</div>
    <div class="stat-lbl">Loan Payment (25yr)</div>
  </div>
  <div class="stat-box">
    <div class="stat-val cf-pos" id="w-cf">+${rec["day1_cashflow_usd"]:.0f}/mo</div>
    <div class="stat-lbl">Day-1 Savings vs Bill</div>
  </div>
  <div class="stat-box">
    <div class="stat-val" id="w-net">${base["net_cost_usd"]:,.0f}</div>
    <div class="stat-lbl">Net Cost After ITC</div>
  </div>
  <div class="stat-box">
    <div class="stat-val cf-pos" id="w-yr1">${base["annual_savings_usd"]:,.0f}/yr</div>
    <div class="stat-lbl">Annual Savings</div>
  </div>
</div>

<div class="table-wrap">
<table id="w-table">
<thead><tr>
  <th>Loan Term</th><th>APR</th><th>Monthly Payment</th>
  <th>vs Your Bill</th><th>Day-1 Cash Flow</th>
</tr></thead>
<tbody id="w-tbody">
  {chr(10).join(
    f"<tr class='{'best' if opt['years'] == rec['years'] else ''}'>"
    f"<td>{opt['label']}</td>"
    f"<td>{opt['apr_pct']}%</td>"
    f"<td>${opt['monthly_payment_usd']:.0f}/mo</td>"
    f"<td>{'saves' if opt['day1_cashflow_usd'] >= 0 else 'costs'} ${abs(opt['day1_cashflow_usd']):.0f}/mo</td>"
    f"<td class='{'cf-pos' if opt['day1_cashflow_usd'] >= 0 else 'cf-neg'}'>"
    f"{'+'if opt['day1_cashflow_usd']>=0 else ''}{opt['day1_cashflow_usd']:.0f}/mo</td>"
    f"</tr>"
    for opt in base["loan_options"]
  )}
</tbody>
</table>
</div>

<div id="w-mode" class="mode-badge">📊 Estimate based on ${bill:.0f}/mo bill — enter address for real data</div>

<div class="cta">
  <div class="cta-head">Ready to own your power for less than your bill?</div>
  {"<div class='cta-phone'>📞 " + phone + "</div>" if phone else ""}
  <div class="cta-sub">{company} — Licensed Solar Specialist</div>
</div>

<script>
const BASE = window.location.origin;
async function fetchCalc() {{
  const bill = parseFloat(document.getElementById('w-bill').value) || 175;
  const addr = document.getElementById('w-addr').value.trim();
  const params = new URLSearchParams({{monthly_bill: bill}});
  if (addr) params.set('address', addr);
  const res = await fetch(`${{BASE}}/api/lead/financing?${{params}}`);
  if (!res.ok) return;
  const d = await res.json();
  renderWidget(d);
}}
function recalc() {{
  const bill = parseFloat(document.getElementById('w-bill').value) || 175;
  // Quick client-side estimate for the best 25yr option
  const kw = (bill / 0.145 * 12 * 0.92) / 1450;
  const net = kw * 1000 * 3.20 * 0.70;
  const pmt = (net * (7.49/100/12) * Math.pow(1+7.49/100/12,300)) / (Math.pow(1+7.49/100/12,300)-1);
  const sav = bill * 0.90;
  const cf  = sav - pmt;
  document.getElementById('w-pmt').textContent = `$${{pmt.toFixed(0)}}/mo`;
  document.getElementById('w-cf').textContent  = `${{cf>=0?'+':''}}$${{Math.abs(cf).toFixed(0)}}/mo`;
  document.getElementById('w-cf').className    = cf >= 0 ? 'stat-val cf-pos' : 'stat-val cf-neg';
  document.getElementById('w-net').textContent = `$${{net.toLocaleString('en-US',{{maximumFractionDigits:0}})}}`;
  document.getElementById('w-yr1').textContent = `$${{(sav*12).toLocaleString('en-US',{{maximumFractionDigits:0}})}}/yr`;
}}
function renderWidget(d) {{
  const rec = d.recommended_option;
  document.getElementById('w-pmt').textContent = `$${{rec.monthly_payment_usd.toFixed(0)}}/mo`;
  const cf = rec.day1_cashflow_usd;
  document.getElementById('w-cf').textContent  = `${{cf>=0?'+':''}}$${{Math.abs(cf).toFixed(0)}}/mo`;
  document.getElementById('w-cf').className    = cf >= 0 ? 'stat-val cf-pos' : 'stat-val cf-neg';
  document.getElementById('w-net').textContent = `$${{d.net_cost_usd.toLocaleString('en-US',{{maximumFractionDigits:0}})}}`;
  document.getElementById('w-yr1').textContent = `$${{d.annual_savings_usd.toLocaleString('en-US',{{maximumFractionDigits:0}})}}/yr`;
  const tbody = document.getElementById('w-tbody');
  tbody.innerHTML = d.loan_options.map(o => {{
    const cf2 = o.day1_cashflow_usd;
    return `<tr class="${{o.years===rec.years?'best':''}}">
      <td>${{o.label}}</td><td>${{o.apr_pct}}%</td>
      <td>$${{o.monthly_payment_usd.toFixed(0)}}/mo</td>
      <td>${{cf2>=0?'saves':'costs'}} $${{Math.abs(cf2).toFixed(0)}}/mo</td>
      <td class="${{cf2>=0?'cf-pos':'cf-neg'}}">${{cf2>=0?'+':''}}$${{cf2.toFixed(0)}}/mo</td>
    </tr>`;
  }}).join('');
  const mode = d.mode === 'enriched' ? `✅ Real solar data for ${{d.address}}` : `📊 Estimate based on $${{d.monthly_bill_usd}}/mo bill`;
  document.getElementById('w-mode').textContent = mode;
}}
</script>
</body>
</html>"""
    return HTMLResponse(content=widget)



# ── GHL Contact Push ──────────────────────────────────────────────────────────

@app.post("/api/lead/ghl-push",
    summary="Push enriched lead to GoHighLevel CRM as a contact",
    tags=["Integrations"])
async def lead_ghl_push(body: dict = Body(...)):
    """
    Enrich a solar lead and push it to GoHighLevel CRM.

    Body:
        address (str): Street address to enrich. Required.
        monthly_bill (float): Monthly electric bill. Default: 175.
        first_name (str): Contact first name. Default: "Solar".
        last_name (str): Contact last name. Default: "Lead".
        email (str): Contact email. Optional.
        phone (str): Contact phone. Optional.
        add_note (bool): Add full analysis as CRM note. Default: True.
        dry_run (bool): Build payload without sending. Default: False.

    Requires env: GHL_API_KEY + GHL_LOCATION_ID
    Returns: {pushed, contact_id, url, tags, ...} or {skipped, reason}
    """
    try:
        from integrations.ghl_push import push_lead_to_ghl
    except ImportError as e:
        raise HTTPException(503, f"GHL integration not available: {e}")

    address      = body.get("address", "")
    monthly_bill = float(body.get("monthly_bill", 175))
    first_name   = body.get("first_name", "Solar")
    last_name    = body.get("last_name", "Lead")
    email        = body.get("email", "")
    phone        = body.get("phone", "")
    add_note     = body.get("add_note", True)
    dry_run      = body.get("dry_run", False)

    if not address:
        raise HTTPException(400, "address is required")

    # Enrich
    lead = None
    try:
        lead = enrich_lead(address)
    except Exception as e:
        lead = {"error": str(e)}

    # Push
    result = push_lead_to_ghl(
        lead or {},
        address,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        add_note=add_note,
        dry_run=dry_run,
    )

    # Attach lead summary to response
    result["lead_score"]          = lead.get("lead_score") if lead else None
    result["grade"]               = lead.get("grade") if lead else None
    result["priority"]            = lead.get("priority") if lead else None
    result["annual_savings_yr1"]  = lead.get("annual_savings_yr1_usd") if lead else None
    result["address"]             = address

    return JSONResponse(result)


@app.get("/api/lead/ghl-push",
    summary="GHL push status / connection test",
    tags=["Integrations"])
async def lead_ghl_push_get(
    test: bool          = Query(False, description="Test GHL API connectivity"),
    address: Optional[str] = Query(None, description="Address to push (with enrichment)"),
    monthly_bill: float = Query(175.0, description="Monthly electric bill"),
    dry_run: bool       = Query(False, description="Build payload without sending"),
):
    """
    GET version: test connection or push a single address.
    - /api/lead/ghl-push?test=true  → connectivity test
    - /api/lead/ghl-push?address=...&dry_run=true  → dry-run push
    """
    try:
        from integrations.ghl_push import push_lead_to_ghl, test_connection
    except ImportError as e:
        raise HTTPException(503, f"GHL integration not available: {e}")

    if test:
        result = test_connection()
        return JSONResponse(result)

    if not address:
        return JSONResponse({
            "info":     "GHL Contact Push — Solar Intelligence Suite",
            "env_set":  {
                "GHL_API_KEY":     bool(os.environ.get("GHL_API_KEY")),
                "GHL_LOCATION_ID": bool(os.environ.get("GHL_LOCATION_ID")),
            },
            "usage":    "POST /api/lead/ghl-push with {address, monthly_bill, first_name, last_name}",
            "test_url": "/api/lead/ghl-push?test=true",
        })

    lead = None
    try:
        lead = enrich_lead(address)
    except Exception as e:
        lead = {"error": str(e)}

    result = push_lead_to_ghl(lead or {}, address, dry_run=dry_run)
    result["lead_score"] = lead.get("lead_score") if lead else None
    result["grade"]      = lead.get("grade") if lead else None
    result["address"]    = address
    return JSONResponse(result)



# ─────────────────────────────────────────────────────────────────────────────
# INCENTIVES ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/incentives",
    summary="Get solar incentives for a state or address",
    tags=["Incentives"])
async def get_incentives_endpoint(
    state: Optional[str]    = Query(None, description="2-letter state code (e.g. AZ)"),
    address: Optional[str]  = Query(None, description="Full address — auto-extracts state"),
    zip_code: Optional[str] = Query(None, description="ZIP code for context"),
    gross_cost: float       = Query(20000.0, description="Gross system cost USD"),
    system_kw: float        = Query(6.0,     description="System size in kW"),
    panels: int             = Query(20,      description="Panel count"),
    monthly_bill: float     = Query(175.0,   description="Monthly electric bill (used to estimate size if cost=0)"),
):
    """
    Returns the complete federal + state + utility incentive stack for a state.

    - `/api/incentives?state=AZ&gross_cost=19200&system_kw=6.4`
    - `/api/incentives?address=1905+E+Marquette+Dr+Gilbert+AZ&gross_cost=19200`
    - `/api/incentives?state=AZ` (uses defaults)
    """
    try:
        from scripts.solar_incentives import get_incentives
    except ImportError as e:
        raise HTTPException(503, f"Incentives module not available: {e}")

    target_state = state
    postal_code  = zip_code

    # Auto-extract state from address
    if not target_state and address:
        parts = address.replace(",", " ").split()
        for p in reversed(parts):
            if len(p) == 2 and p.isalpha():
                target_state = p.upper()
                break
        # Try geocoding for state if address given
        if not target_state:
            try:
                geo = geocode_address(address)
                if "state" in geo:
                    target_state = geo["state"]
                if "postal_code" in geo:
                    postal_code = geo["postal_code"]
            except Exception:
                pass

    if not target_state:
        target_state = "AZ"

    result = get_incentives(
        state=target_state,
        postal_code=postal_code,
        gross_cost_usd=gross_cost,
        system_size_kw=system_kw,
        panel_count=panels,
    )
    return JSONResponse(result)


@app.get("/api/incentives/states",
    summary="List all states with tracked incentives",
    tags=["Incentives"])
async def list_incentive_states():
    """Returns all states with known state-level solar incentives beyond federal ITC."""
    try:
        from scripts.solar_incentives import STATE_INCENTIVES, list_states_with_incentives
    except ImportError as e:
        raise HTTPException(503, f"Incentives module not available: {e}")

    states = list_states_with_incentives()
    return JSONResponse({
        "states_with_incentives": [
            {
                "state": s,
                "program_count": len(STATE_INCENTIVES[s]),
                "programs": [inc["name"] for inc in STATE_INCENTIVES[s]],
            }
            for s in states
        ],
        "total_states_tracked": len(states),
        "note": "Federal ITC (30%) applies in all 50 states.",
    })


@app.get("/api/lead/incentives",
    summary="Incentive stack for a specific lead address",
    tags=["Incentives"])
async def lead_incentives(
    address: str        = Query(..., description="Address to enrich and look up incentives"),
    monthly_bill: float = Query(175.0, description="Monthly electric bill"),
    utility_rate: float = Query(DEFAULT_UTILITY_RATE_KWH, description="Utility rate $/kWh"),
):
    """
    Enriches a lead AND returns the full incentive stack together.
    Returns merged lead data + complete incentive breakdown.
    Great for proposal generation and dashboard integration.
    """
    try:
        from scripts.solar_incentives import get_incentives
    except ImportError as e:
        raise HTTPException(503, f"Incentives module not available: {e}")

    # Enrich lead
    lead = enrich_lead(address, monthly_bill=monthly_bill, utility_rate=utility_rate)
    if "error" in lead:
        raise HTTPException(422, f"Lead enrichment failed: {lead['error']}")

    # Look up incentives
    incentives = get_incentives(
        state=lead.get("state", "AZ"),
        postal_code=lead.get("postal_code"),
        gross_cost_usd=lead.get("gross_cost_usd", 20000),
        system_size_kw=lead.get("system_size_kw", 6.0),
        panel_count=lead.get("panels_recommended", 20),
    )

    return JSONResponse({
        **lead,
        "incentives": incentives,
        "total_incentive_savings_usd": incentives["total_savings_usd"],
        "net_cost_with_all_incentives": incentives["net_cost_after_incentives"],
        "effective_discount_pct": incentives["effective_discount_pct"],
        "incentive_summary": incentives["summary_line"],
    })


# ─── OBJECTION HANDLER ENDPOINTS ─────────────────────────────────────────────

@app.get("/api/objections")
def list_objections_api():
    """List all 10 objection types with keywords."""
    try:
        from scripts.objection_handler import list_objections
    except ImportError as e:
        raise HTTPException(503, f"Objection handler not available: {e}")
    return JSONResponse({"objections": list_objections(), "total": 10})


@app.get("/api/objections/{objection_key}")
def get_objection_rebuttals(
    objection_key: str,
    address: str = Query(None, description="Homeowner address for personalized data"),
    monthly_bill: float = Query(175.0, description="Monthly electric bill"),
    utility_rate: float = Query(0.14),
):
    """
    Get personalized rebuttal script for a specific objection.
    objection_key: number (1-10), id (e.g. 'too_expensive'), or keyword phrase.
    """
    try:
        from scripts.objection_handler import get_rebuttals
    except ImportError as e:
        raise HTTPException(503, f"Objection handler not available: {e}")

    lead = None
    if address:
        lead = enrich_lead(address, monthly_bill=monthly_bill, utility_rate=utility_rate)

    result = get_rebuttals(objection_key, lead=lead, monthly_bill=monthly_bill)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return JSONResponse(result)


@app.post("/api/objections/match")
async def match_objection(request: Request):
    """
    Match an objection from free-form text and return rebuttal script.
    Body: {query, address?, monthly_bill?, utility_rate?}
    """
    try:
        from scripts.objection_handler import get_rebuttals
    except ImportError as e:
        raise HTTPException(503, f"Objection handler not available: {e}")

    body = await request.json()
    query = body.get("query", "")
    if not query:
        raise HTTPException(400, "query is required")

    address = body.get("address")
    monthly_bill = float(body.get("monthly_bill", 175.0))
    utility_rate = float(body.get("utility_rate", 0.14))

    lead = None
    if address:
        lead = enrich_lead(address, monthly_bill=monthly_bill, utility_rate=utility_rate)

    result = get_rebuttals(query, lead=lead, monthly_bill=monthly_bill)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return JSONResponse(result)


# ─── DOOR-KNOCK SCRIPT ENDPOINTS ─────────────────────────────────────────────

@app.get("/api/lead/door-script")
async def door_knock_script_get(
    address: str = Query(..., description="Homeowner address"),
    monthly_bill: float = Query(175.0, description="Monthly electric bill USD"),
    utility_rate: float = Query(0.14),
):
    """
    Generate a personalized door-knock sales script for the given address.
    Returns a full 5-step script: Opener, Discovery, Pivot, Proof Points, Close.
    """
    try:
        from scripts.door_knock_script import generate_door_knock_script
    except ImportError as e:
        raise HTTPException(503, f"Door knock script module not available: {e}")

    lead = enrich_lead(address, monthly_bill=monthly_bill, utility_rate=utility_rate)
    result = generate_door_knock_script(lead, monthly_bill=monthly_bill)
    return JSONResponse(result)


@app.post("/api/lead/door-script")
async def door_knock_script_post(request: Request):
    """
    POST body: {"address": "...", "monthly_bill": 175, "utility_rate": 0.14}
    Returns personalized door-knock script JSON.
    """
    try:
        from scripts.door_knock_script import generate_door_knock_script
    except ImportError as e:
        raise HTTPException(503, f"Door knock script module not available: {e}")

    body = await request.json()
    address = body.get("address")
    monthly_bill = float(body.get("monthly_bill", 175.0))
    utility_rate = float(body.get("utility_rate", 0.14))

    lead = None
    if address:
        lead = enrich_lead(address, monthly_bill=monthly_bill, utility_rate=utility_rate)

    result = generate_door_knock_script(lead, monthly_bill=monthly_bill)
    return JSONResponse(result)


# ═══════════════════════════════════════════════════════════════════════════════
# BONUS O — Lead Pipeline CRM
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/pipeline/leads",
    summary="List all pipeline leads",
    tags=["Pipeline CRM"])
async def pipeline_list(stage: str = None, limit: int = 100):
    """List leads in the pipeline, optionally filtered by stage."""
    try:
        from scripts.pipeline import PipelineCRM
        crm = PipelineCRM()
        leads = crm.list_leads(stage=stage, limit=limit)
        return JSONResponse({"leads": leads, "count": len(leads)})
    except Exception as e:
        raise HTTPException(500, f"Pipeline error: {e}")


@app.post("/api/pipeline/leads",
    summary="Add a lead to the pipeline",
    tags=["Pipeline CRM"])
async def pipeline_add(request: Request):
    """
    Add a new lead to the pipeline.

    Body:
        address (str): Property address
        contact_name (str): Homeowner name
        phone (str): Phone number
        email (str): Email
        monthly_bill (float): Average electric bill
        enrich (bool): Whether to call Solar API (default true)
        source (str): Lead source label
    """
    try:
        from scripts.pipeline import PipelineCRM
        crm = PipelineCRM()
    except Exception as e:
        raise HTTPException(503, f"Pipeline module unavailable: {e}")

    body = await request.json()
    address = body.get("address", "")
    lead_id = crm.add_lead(
        address=address,
        contact_name=body.get("contact_name", ""),
        phone=body.get("phone", ""),
        email=body.get("email", ""),
        monthly_bill=float(body.get("monthly_bill", 0)),
        enrich=body.get("enrich", True),
        source=body.get("source", "api"),
    )
    lead = crm.get_lead(lead_id)
    return JSONResponse({"ok": True, "lead_id": lead_id, "lead": lead})


@app.get("/api/pipeline/leads/{lead_id}",
    summary="Get a single pipeline lead",
    tags=["Pipeline CRM"])
async def pipeline_get_lead(lead_id: int):
    """Get full detail for a single lead including notes and stage history."""
    try:
        from scripts.pipeline import PipelineCRM
        crm = PipelineCRM()
        lead = crm.get_lead(lead_id)
        if not lead:
            raise HTTPException(404, f"Lead #{lead_id} not found")
        return JSONResponse(lead)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Pipeline error: {e}")


@app.post("/api/pipeline/leads/{lead_id}/move",
    summary="Move lead to a new stage",
    tags=["Pipeline CRM"])
async def pipeline_move(lead_id: int, request: Request):
    """
    Advance or change a lead's pipeline stage.

    Body:
        stage (str): One of new, contacted, qualified, proposed, closed_won, closed_lost
    """
    try:
        from scripts.pipeline import PipelineCRM, STAGES
        crm = PipelineCRM()
    except Exception as e:
        raise HTTPException(503, f"Pipeline module unavailable: {e}")

    body = await request.json()
    stage = body.get("stage", "")
    if stage not in STAGES:
        raise HTTPException(400, f"Invalid stage '{stage}'. Valid: {STAGES}")
    ok = crm.move_stage(lead_id, stage)
    if not ok:
        raise HTTPException(404, f"Lead #{lead_id} not found")
    return JSONResponse({"ok": True, "lead_id": lead_id, "new_stage": stage})


@app.post("/api/pipeline/leads/{lead_id}/note",
    summary="Add a note to a pipeline lead",
    tags=["Pipeline CRM"])
async def pipeline_note(lead_id: int, request: Request):
    """
    Add a note/activity log entry to a lead.

    Body:
        note (str): Note text
        author (str): Rep name/identifier (default: 'rep')
    """
    try:
        from scripts.pipeline import PipelineCRM
        crm = PipelineCRM()
    except Exception as e:
        raise HTTPException(503, f"Pipeline module unavailable: {e}")

    body = await request.json()
    note = body.get("note", "").strip()
    if not note:
        raise HTTPException(400, "note cannot be empty")
    ok = crm.add_note(lead_id, note, author=body.get("author", "rep"))
    if not ok:
        raise HTTPException(404, f"Lead #{lead_id} not found")
    return JSONResponse({"ok": True, "lead_id": lead_id})


@app.post("/api/pipeline/leads/{lead_id}/deal",
    summary="Set deal value for a lead",
    tags=["Pipeline CRM"])
async def pipeline_deal(lead_id: int, request: Request):
    """Set the expected/actual deal value in dollars for a lead."""
    try:
        from scripts.pipeline import PipelineCRM
        crm = PipelineCRM()
        body = await request.json()
        value = float(body.get("value", 0))
        ok = crm.set_deal_value(lead_id, value)
        if not ok:
            raise HTTPException(404, f"Lead #{lead_id} not found")
        return JSONResponse({"ok": True, "lead_id": lead_id, "deal_value": value})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Pipeline error: {e}")


@app.get("/api/pipeline/stats",
    summary="Pipeline summary statistics",
    tags=["Pipeline CRM"])
async def pipeline_stats():
    """Get counts, average scores, and revenue by pipeline stage."""
    try:
        from scripts.pipeline import PipelineCRM
        crm = PipelineCRM()
        return JSONResponse(crm.stats())
    except Exception as e:
        raise HTTPException(500, f"Pipeline error: {e}")


@app.post("/api/pipeline/import-cache",
    summary="Import enriched leads from cache",
    tags=["Pipeline CRM"])
async def pipeline_import(max_leads: int = 20):
    """Scan the cache folder and import quality leads (score ≥ 50) into the pipeline."""
    try:
        from scripts.pipeline import PipelineCRM
        crm = PipelineCRM()
        n = crm.import_from_cache(max_leads=max_leads)
        stats = crm.stats()
        return JSONResponse({"ok": True, "imported": n, "pipeline_stats": stats})
    except Exception as e:
        raise HTTPException(500, f"Pipeline import error: {e}")



# ─── Report Card Endpoints ────────────────────────────────────────────────────

@app.get("/api/lead/report-card",
    summary="Generate a homeowner solar report card (HTML)",
    tags=["Lead Tools"])
async def report_card_get(
    address: str = Query(..., description="Property address"),
    monthly_bill: float = Query(175.0, description="Monthly utility bill in USD"),
    utility_rate: float = Query(0.14, description="Utility rate per kWh"),
    rep_name: str = Query("", description="Rep's name for footer"),
    rep_phone: str = Query("", description="Rep's phone for CTA"),
    rep_company: str = Query("Solar Intelligence", description="Company name"),
):
    """
    Generate a standalone, mobile-responsive homeowner solar report card.
    Returns full HTML — suitable for texting/emailing the link to the homeowner.
    """
    try:
        from scripts.report_card import generate_report_card
        result = generate_report_card(
            address,
            monthly_bill=monthly_bill,
            utility_rate=utility_rate,
            rep_name=rep_name,
            rep_phone=rep_phone,
            rep_company=rep_company,
        )
        if result.get("error"):
            raise HTTPException(400, result["error"])
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=result["html"], status_code=200)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Report card error: {e}")


@app.post("/api/lead/report-card",
    summary="Generate a homeowner solar report card (POST)",
    tags=["Lead Tools"])
async def report_card_post(request: Request):
    """
    Generate a homeowner solar report card HTML page.
    Body: {address, monthly_bill, utility_rate, rep_name, rep_phone, rep_company}
    Returns standalone HTML.
    """
    try:
        from scripts.report_card import generate_report_card
        from fastapi.responses import HTMLResponse
        body = await request.json()
        address = body.get("address", "")
        if not address:
            raise HTTPException(400, "address is required")
        result = generate_report_card(
            address,
            monthly_bill=float(body.get("monthly_bill", 175)),
            utility_rate=float(body.get("utility_rate", 0.14)),
            rep_name=body.get("rep_name", ""),
            rep_phone=body.get("rep_phone", ""),
            rep_company=body.get("rep_company", "Solar Intelligence"),
        )
        if result.get("error"):
            raise HTTPException(400, result["error"])
        return HTMLResponse(content=result["html"], status_code=200)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Report card error: {e}")


@app.get("/api/lead/report-card/json",
    summary="Generate report card — return JSON summary instead of HTML",
    tags=["Lead Tools"])
async def report_card_json(
    address: str = Query(..., description="Property address"),
    monthly_bill: float = Query(175.0),
    utility_rate: float = Query(0.14),
    rep_name: str = Query(""),
    rep_phone: str = Query(""),
    rep_company: str = Query("Solar Intelligence"),
):
    """Returns JSON metadata (not HTML) for the generated report card."""
    try:
        from scripts.report_card import generate_report_card
        result = generate_report_card(
            address,
            monthly_bill=monthly_bill,
            utility_rate=utility_rate,
            rep_name=rep_name,
            rep_phone=rep_phone,
            rep_company=rep_company,
        )
        if result.get("error"):
            raise HTTPException(400, result["error"])
        lead = result["lead"]
        return JSONResponse({
            "address": lead.get("address"),
            "score": lead.get("lead_score"),
            "grade": lead.get("lead_grade"),
            "priority": lead.get("priority"),
            "annual_savings_yr1": lead.get("annual_savings_yr1_usd"),
            "net_cost_usd": lead.get("net_cost_usd"),
            "payback_years": lead.get("payback_years"),
            "roi_25yr_pct": lead.get("roi_25yr_pct"),
            "system_kw": lead.get("system_size_kw"),
            "panels": lead.get("panels_recommended"),
            "sunshine_hours": lead.get("sunshine_hours_per_year"),
            "saved_to": result["path"],
            "rep_name": rep_name,
            "rep_company": rep_company,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Report card JSON error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# WIDGET ENDPOINTS — Embeddable Solar Savings Calculator
# ─────────────────────────────────────────────────────────────────────────────

import sqlite3, datetime as _dt

WIDGET_DB = "/root/solar-tools/cache/widget_leads.db"

def _widget_db():
    """Return a connection to the widget leads SQLite DB, creating table if needed."""
    conn = sqlite3.connect(WIDGET_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS widget_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submitted_at TEXT NOT NULL,
            address TEXT,
            name TEXT,
            phone TEXT,
            email TEXT,
            monthly_bill REAL,
            lead_score INTEGER,
            lead_grade TEXT,
            priority TEXT,
            annual_savings REAL,
            utm_source TEXT,
            utm_campaign TEXT,
            widget_company TEXT,
            estimated INTEGER DEFAULT 0,
            raw_json TEXT
        )
    """)
    conn.commit()
    return conn


@app.get("/api/widget/embed.js",
    summary="Serve the embeddable Solar widget JavaScript",
    tags=["Widget"])
async def widget_embed_js(request: Request):
    """
    Serves the standalone JavaScript widget. All query params are forwarded
    to the widget config at runtime via the script src URL.

    Usage:
        <script src="http://localhost:8765/api/widget/embed.js?company=Elevate+Solar&primary=%2316a34a" async></script>
    """
    js_path = "/root/solar-tools/web/embed.js"
    try:
        js = open(js_path).read()
    except FileNotFoundError:
        raise HTTPException(404, "Widget JS not found. Build web/embed.js first.")
    return Response(
        content=js,
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=300",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/api/widget/demo",
    summary="Live demo page for the embeddable widget",
    tags=["Widget"],
    response_class=HTMLResponse)
async def widget_demo():
    """Returns the widget demo/documentation page."""
    html_path = "/root/solar-tools/web/widget_demo.html"
    try:
        return HTMLResponse(open(html_path).read())
    except FileNotFoundError:
        raise HTTPException(404, "Demo page not found.")


@app.get("/api/widget/snippet",
    summary="Generate embed snippet for any config",
    tags=["Widget"])
async def widget_snippet(
    company:     str = Query("Solar Intelligence", description="Company name"),
    tagline:     str = Query("Find out how much you could save"),
    primary:     str = Query("#16a34a", description="Accent color hex"),
    mode:        str = Query("floating", description="floating | inline | button"),
    target:      str = Query("", description="CSS selector (inline mode only)"),
    phone:       str = Query("", description="Rep phone for thank-you screen"),
    rep:         str = Query("", description="Rep name for thank-you screen"),
    utm_source:  str = Query("website"),
    utm_campaign:str = Query(""),
    server_url:  str = Query("http://localhost:8765", description="Base URL of this server"),
):
    """Returns embed snippet code for copy-paste into any website."""
    import urllib.parse
    params = {
        "company": company,
        "tagline": tagline,
        "primary": primary.replace("#", "%23"),
        "mode": mode,
    }
    if target:      params["target"]       = target
    if phone:       params["phone"]        = phone
    if rep:         params["rep"]          = rep
    if utm_source:  params["utm_source"]   = utm_source
    if utm_campaign:params["utm_campaign"] = utm_campaign

    qs = "&".join(f"{k}={urllib.parse.quote(str(v), safe='%')}" for k, v in params.items())
    src = f"{server_url}/api/widget/embed.js?{qs}"
    snippet = f'<!-- Solar Savings Calculator Widget by {company} -->\n<script src="{src}" async></script>'

    return JSONResponse({
        "snippet": snippet,
        "src": src,
        "config": params,
        "demo_url": f"{server_url}/api/widget/demo",
        "leads_url": f"{server_url}/api/widget/leads",
    })


class WidgetLeadRequest(BaseModel):
    address: str = ""
    name: str = ""
    phone: str = ""
    email: str = ""
    monthly_bill: float = 175.0
    lead_score: Optional[int] = None
    lead_grade: Optional[str] = None
    priority: Optional[str] = None
    annual_savings: Optional[float] = None
    utm_source: str = "embed_widget"
    utm_campaign: str = ""
    widget_company: str = ""
    estimated: bool = False


@app.post("/api/widget/submit",
    summary="Receive lead from embedded widget",
    tags=["Widget"])
async def widget_submit(req: WidgetLeadRequest):
    """
    Called by the embedded widget when a homeowner submits their contact info.
    Saves to widget_leads SQLite DB + fires Discord notification if configured.

    Fields saved: address, name, phone, email, bill, score, grade, priority,
                  annual_savings, UTM params, widget_company, estimated flag.
    """
    now = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    raw = req.model_dump()

    try:
        conn = _widget_db()
        conn.execute("""
            INSERT INTO widget_leads
              (submitted_at, address, name, phone, email, monthly_bill,
               lead_score, lead_grade, priority, annual_savings,
               utm_source, utm_campaign, widget_company, estimated, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            now,
            req.address, req.name, req.phone, req.email,
            req.monthly_bill, req.lead_score, req.lead_grade,
            req.priority, req.annual_savings,
            req.utm_source, req.utm_campaign, req.widget_company,
            1 if req.estimated else 0,
            json.dumps(raw),
        ))
        conn.commit()
        lead_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
    except Exception as e:
        lead_id = None
        # Don't crash widget — log and continue
        print(f"[Widget] DB error: {e}")

    # Discord notification for HOT/WARM priority captures
    if _discord_enabled and req.priority in ("HOT", "WARM"):
        try:
            from integrations.discord_alerts import post_message
            score_str = f"{req.lead_score}/100" if req.lead_score else "~72/100"
            savings_str = f"${req.annual_savings:,.0f}/yr" if req.annual_savings else "TBD"
            msg = (
                f"🌐 **New Widget Lead — {req.priority}!**\n"
                f"**Name:** {req.name}  |  **Phone:** {req.phone}"
                + (f"  |  **Email:** {req.email}" if req.email else "") + "\n"
                f"**Address:** {req.address}\n"
                f"**Score:** {score_str}  |  **Est. savings:** {savings_str}\n"
                f"**Source:** {req.utm_source}"
                + (f"  |  **Campaign:** {req.utm_campaign}" if req.utm_campaign else "")
                + (f"\n*Estimated (API fallback mode)*" if req.estimated else "")
            )
            post_message(msg)
        except Exception:
            pass

    return JSONResponse({
        "ok": True,
        "lead_id": lead_id,
        "message": f"Lead captured — thank you, {req.name.split()[0] if req.name else 'there'}!",
        "address": req.address,
        "priority": req.priority,
    })


@app.get("/api/widget/leads",
    summary="List all widget-captured leads",
    tags=["Widget"])
async def widget_leads(
    limit: int = Query(100, ge=1, le=500),
    priority: str = Query("", description="Filter by priority: HOT, WARM, COOL"),
    since_hours: int = Query(0, description="Only return leads from last N hours (0=all)"),
):
    """
    Returns all leads captured via the embeddable widget, sorted newest first.
    Useful for reviewing overnight widget submissions in the dashboard.
    """
    try:
        conn = _widget_db()
        sql = "SELECT * FROM widget_leads WHERE 1=1"
        params = []
        if priority:
            sql += " AND priority = ?"
            params.append(priority.upper())
        if since_hours:
            cutoff = (_dt.datetime.utcnow() - _dt.timedelta(hours=since_hours)).strftime("%Y-%m-%d %H:%M:%S")
            sql += " AND submitted_at >= ?"
            params.append(cutoff)
        sql += " ORDER BY submitted_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM widget_leads LIMIT 0").description]
        conn.close()

        leads_out = []
        for row in rows:
            d = dict(zip(cols, row))
            d.pop("raw_json", None)  # omit raw blob
            leads_out.append(d)

        hot_count  = sum(1 for r in leads_out if r.get("priority") == "HOT")
        warm_count = sum(1 for r in leads_out if r.get("priority") == "WARM")

        return JSONResponse({
            "total": len(leads_out),
            "hot_leads": hot_count,
            "warm_leads": warm_count,
            "leads": leads_out,
        })
    except Exception as e:
        raise HTTPException(500, f"Widget leads error: {e}")



# ── /api/lead/appointment-setter ──────────────────────────────────────────────

@app.get("/api/lead/appointment-setter")
async def appointment_setter_get(
    address: str | None = None,
    monthly_bill: float = 175.0,
    utility_rate: float = 0.14,
    rep_name: str = "[YOUR NAME]",
    rep_phone: str = "[YOUR PHONE]",
    rep_company: str = "our solar team",
    no_enrich: bool = False,
):
    """
    Generate a full appointment-setting comms kit for a property.
    Returns: phone_script, voicemail, sms_sequence, email_intro, email_followup,
             confirm_sms, confirm_email — all personalized with real solar data.
    """
    try:
        from scripts.appointment_setter import generate_appointment_kit
        lead = None
        if address and not no_enrich:
            try:
                lead = enrich_lead(address, monthly_bill, utility_rate)
                if lead.get("error"):
                    lead = None
            except Exception:
                lead = None

        kit = generate_appointment_kit(
            lead=lead,
            monthly_bill=monthly_bill,
            rep_name=rep_name,
            rep_phone=rep_phone,
            rep_company=rep_company,
        )
        return JSONResponse(kit)
    except Exception as e:
        raise HTTPException(500, f"Appointment setter error: {e}")


@app.post("/api/lead/appointment-setter")
async def appointment_setter_post(request: Request):
    """
    POST version — body: {address, monthly_bill, utility_rate, rep_name, rep_phone, rep_company, no_enrich}
    """
    try:
        from scripts.appointment_setter import generate_appointment_kit
        body = await request.json()
        address      = body.get("address")
        monthly_bill = float(body.get("monthly_bill", 175))
        utility_rate = float(body.get("utility_rate", 0.14))
        rep_name     = body.get("rep_name", "[YOUR NAME]")
        rep_phone    = body.get("rep_phone", "[YOUR PHONE]")
        rep_company  = body.get("rep_company", "our solar team")
        no_enrich    = bool(body.get("no_enrich", False))

        lead = None
        if address and not no_enrich:
            try:
                lead = enrich_lead(address, monthly_bill, utility_rate)
                if lead.get("error"):
                    lead = None
            except Exception:
                lead = None

        kit = generate_appointment_kit(
            lead=lead,
            monthly_bill=monthly_bill,
            rep_name=rep_name,
            rep_phone=rep_phone,
            rep_company=rep_company,
        )
        return JSONResponse(kit)
    except Exception as e:
        raise HTTPException(500, f"Appointment setter error: {e}")



# ─────────────────────────────────────────────────────────────────────────────
# 90-Day Drip Campaign Generator
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/lead/drip-campaign",
    summary="90-day lead nurture drip campaign (GET, address or bill-only)",
    tags=["Lead Intelligence"])
async def drip_campaign_get(
    address: str = None,
    monthly_bill: float = 175.0,
    utility_rate: float = 0.14,
    stage: str = "new",
    contact_name: str = "",
    email: str = "",
    rep_name: str = "Your Solar Rep",
    rep_phone: str = "602-555-0100",
    company: str = "Elevate Solar",
    format: str = "json",
):
    """
    Generate a 90-day drip campaign for a lead.

    - **address** – home address (optional; enriches via Solar API + cache)
    - **stage** – pipeline stage: new | contacted | qualified | proposed
    - **format** – json (default) | csv (GHL-importable CSV text)

    Returns personalized email + SMS sequence with real solar data injected.
    """
    try:
        from scripts.drip_campaign import generate_drip_campaign, export_csv

        valid_stages = ["new", "contacted", "qualified", "proposed"]
        if stage not in valid_stages:
            raise HTTPException(400, f"stage must be one of: {valid_stages}")

        lead = {}
        if address:
            try:
                lead = enrich_lead(address, monthly_bill, utility_rate)
                if lead.get("error"):
                    lead = {"address": address}
            except Exception:
                lead = {"address": address}

        campaign = generate_drip_campaign(
            lead, stage=stage, monthly_bill=monthly_bill,
            rep_name=rep_name, rep_phone=rep_phone,
            company=company, contact_name=contact_name, email=email
        )

        if format == "csv":
            csv_text = export_csv(campaign)
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(csv_text, media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="drip_{stage}.csv"'})

        # Strip csv_rows from JSON response (large, redundant with messages)
        campaign.pop("csv_rows", None)
        return JSONResponse(campaign)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Drip campaign error: {e}")


@app.post("/api/lead/drip-campaign",
    summary="90-day lead nurture drip campaign (POST)",
    tags=["Lead Intelligence"])
async def drip_campaign_post(request: Request):
    """
    POST version — full control over all parameters.

    Body:
    ```json
    {
      "address": "1905 E Marquette Dr, Gilbert AZ",
      "monthly_bill": 175,
      "utility_rate": 0.14,
      "stage": "new",
      "contact_name": "Sarah Martinez",
      "email": "sarah@example.com",
      "rep_name": "Jake Rivera",
      "rep_phone": "602-555-0100",
      "company": "Elevate Solar",
      "pipeline_lead_id": 1,
      "format": "json"
    }
    ```
    Set **pipeline_lead_id** to auto-load contact info + stage from pipeline DB.
    Set **format**: "json" | "csv" for GHL-importable output.
    """
    try:
        from scripts.drip_campaign import generate_drip_campaign, export_csv

        body = await request.json()
        address      = body.get("address")
        monthly_bill = float(body.get("monthly_bill", 175))
        utility_rate = float(body.get("utility_rate", 0.14))
        stage        = body.get("stage", "new")
        contact_name = body.get("contact_name", "")
        email_addr   = body.get("email", "")
        rep_name     = body.get("rep_name", "Your Solar Rep")
        rep_phone    = body.get("rep_phone", "602-555-0100")
        company      = body.get("company", "Elevate Solar")
        pipeline_id  = body.get("pipeline_lead_id")
        fmt          = body.get("format", "json")

        valid_stages = ["new", "contacted", "qualified", "proposed"]

        # Load from pipeline if ID provided
        if pipeline_id:
            try:
                from scripts.pipeline import PipelineCRM
                db = PipelineCRM()
                rec = db.get_lead(int(pipeline_id))
                if rec:
                    address = address or rec.get("address", "")
                    contact_name = contact_name or rec.get("contact_name", "")
                    email_addr = email_addr or rec.get("email", "")
                    monthly_bill = monthly_bill if body.get("monthly_bill") else rec.get("monthly_bill", monthly_bill)
                    stage = stage if body.get("stage") else rec.get("stage", stage)
            except Exception:
                pass

        if stage not in valid_stages:
            stage = "new"

        lead = {}
        if address:
            try:
                lead = enrich_lead(address, monthly_bill, utility_rate)
                if lead.get("error"):
                    lead = {"address": address}
            except Exception:
                lead = {"address": address}

        campaign = generate_drip_campaign(
            lead, stage=stage, monthly_bill=monthly_bill,
            rep_name=rep_name, rep_phone=rep_phone,
            company=company, contact_name=contact_name, email=email_addr
        )

        if fmt == "csv":
            csv_text = export_csv(campaign)
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(csv_text, media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="drip_{stage}.csv"'})

        campaign.pop("csv_rows", None)
        return JSONResponse(campaign)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Drip campaign error: {e}")


@app.get("/api/lead/drip-campaign/stages",
    summary="List available drip campaign stages",
    tags=["Lead Intelligence"])
async def drip_stages():
    """Returns available pipeline stages and message counts per stage."""
    try:
        from scripts.drip_campaign import CAMPAIGNS, STAGE_INTRO
        stages = []
        for stage, steps in CAMPAIGNS.items():
            sms_count = sum(1 for s in steps if s["channel"] == "sms")
            email_count = sum(1 for s in steps if s["channel"] == "email")
            total_days = max(s["day"] for s in steps) if steps else 0
            stages.append({
                "stage": stage,
                "label": STAGE_INTRO.get(stage, stage),
                "message_count": len(steps),
                "sms_count": sms_count,
                "email_count": email_count,
                "total_days": total_days,
            })
        return JSONResponse({"stages": stages, "total": len(stages)})
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# MORNING REP BRIEFING
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/lead/morning-briefing",
    summary="Morning rep briefing — who to call today",
    tags=["Lead Intelligence"])
async def morning_briefing_get(
    rep: str = Query("Solar Rep", description="Rep name"),
    city: str = Query("Phoenix,AZ", description="City for weather (e.g. Phoenix,AZ)"),
    format: str = Query("json", description="'json' or 'text'"),
):
    """
    Daily morning briefing: pipeline follow-ups, hot leads, weather conditions,
    door-knock openers, and a pipeline snapshot.
    """
    try:
        from scripts.morning_briefing import generate_briefing, save_briefing
        result = generate_briefing(rep_name=rep, city=city, use_color=False)
        if format == "text":
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(result["plain_text"])
        # Save for reference
        save_briefing(result["plain_text"])
        result.pop("formatted_text", None)
        result.pop("plain_text", None)
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(500, f"Morning briefing error: {e}")


@app.post("/api/lead/morning-briefing",
    summary="Morning rep briefing (POST)",
    tags=["Lead Intelligence"])
async def morning_briefing_post(request: Request):
    """POST version: body {rep_name, city, format}"""
    try:
        from scripts.morning_briefing import generate_briefing, save_briefing
        body = await request.json()
        rep  = body.get("rep_name", "Solar Rep")
        city = body.get("city", "Phoenix,AZ")
        fmt  = body.get("format", "json")
        result = generate_briefing(rep_name=rep, city=city, use_color=False)
        if fmt == "text":
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(result["plain_text"])
        save_briefing(result["plain_text"])
        result.pop("formatted_text", None)
        result.pop("plain_text", None)
        return JSONResponse(result)
    except Exception as e:
        raise HTTPException(500, f"Morning briefing error: {e}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)
