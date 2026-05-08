"""
GHL (GoHighLevel) Webhook Integration Template
Receives inbound leads from GHL, enriches with Solar API,
posts back enriched data to the GHL contact + tags them by lead grade.

Deploy this alongside the main API server.
"""
import sys, os, json, httpx
sys.path.insert(0, "/root/solar-tools")

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from core.solar import enrich_lead
from typing import Optional

app = FastAPI(title="GHL Solar Webhook Handler")

# ── GHL config (set in env) ───────────────────────────────────────────────────
GHL_API_KEY = os.environ.get("GHL_API_KEY", "")
GHL_BASE_URL = "https://rest.gohighlevel.com/v1"


async def update_ghl_contact(contact_id: str, solar_data: dict):
    """Push enriched solar data back to the GHL contact's custom fields."""
    if not GHL_API_KEY:
        print("⚠️  GHL_API_KEY not set — skipping CRM update")
        return

    # Map solar data → GHL custom field names
    # (These field keys need to match your GHL custom field IDs)
    custom_fields = [
        {"id": "solar_lead_score",     "field_value": str(solar_data.get("lead_score", 0))},
        {"id": "solar_lead_grade",     "field_value": solar_data.get("lead_grade", "")},
        {"id": "solar_system_kw",      "field_value": str(solar_data.get("system_size_kw", 0))},
        {"id": "solar_annual_savings", "field_value": str(solar_data.get("annual_savings_yr1_usd", 0))},
        {"id": "solar_net_cost",       "field_value": str(solar_data.get("net_cost_usd", 0))},
        {"id": "solar_payback_years",  "field_value": str(solar_data.get("payback_years", 0))},
        {"id": "solar_panels",         "field_value": str(solar_data.get("panels_recommended", 0))},
        {"id": "solar_priority",       "field_value": solar_data.get("priority", "UNKNOWN")},
        {"id": "solar_sunshine_hrs",   "field_value": str(solar_data.get("sunshine_hours_per_year", 0))},
        {"id": "solar_25yr_roi",       "field_value": str(solar_data.get("roi_25yr_pct", 0))},
    ]

    # Add talking points as a note
    talking_points = solar_data.get("talking_points", [])
    note_body = "☀️ SOLAR PRE-ANALYSIS (Auto-generated)\n\n"
    note_body += "\n".join(talking_points)

    async with httpx.AsyncClient() as client:
        # Update contact custom fields
        resp = await client.put(
            f"{GHL_BASE_URL}/contacts/{contact_id}",
            headers={"Authorization": f"Bearer {GHL_API_KEY}"},
            json={"customField": custom_fields}
        )
        print(f"GHL contact update: {resp.status_code}")

        # Add note with talking points
        note_resp = await client.post(
            f"{GHL_BASE_URL}/contacts/{contact_id}/notes",
            headers={"Authorization": f"Bearer {GHL_API_KEY}"},
            json={"body": note_body, "userId": "system"}
        )
        print(f"GHL note added: {note_resp.status_code}")

        # Add tag based on lead grade
        priority = solar_data.get("priority", "")
        tag = f"solar-{priority.lower()}" if priority else "solar-analyzed"
        tag_resp = await client.post(
            f"{GHL_BASE_URL}/contacts/{contact_id}/tags",
            headers={"Authorization": f"Bearer {GHL_API_KEY}"},
            json={"tags": [tag, "solar-pre-analyzed"]}
        )
        print(f"GHL tag applied: {tag_resp.status_code}")


@app.post("/webhook/ghl/new-lead")
async def handle_new_lead(request: Request):
    """
    Webhook endpoint for GHL 'Contact Created' or 'Form Submitted' events.
    
    Set up in GHL: Automations → Webhook → POST to this URL
    
    Expected payload (GHL sends contact data):
    {
        "contact_id": "abc123",
        "address1": "123 Main St",
        "city": "Phoenix",
        "state": "AZ",
        "postal_code": "85001",
        "customField": {
            "monthly_electric_bill": "175"
        }
    }
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    contact_id = payload.get("contact_id") or payload.get("id")
    
    # Build address from GHL fields
    address_parts = [
        payload.get("address1", ""),
        payload.get("city", ""),
        payload.get("state", ""),
        payload.get("postal_code", ""),
    ]
    address = ", ".join(p for p in address_parts if p).strip(", ")

    if not address or len(address) < 10:
        return JSONResponse({"status": "skipped", "reason": "No usable address in payload"})

    # Get monthly bill from custom fields if available
    custom = payload.get("customField", {})
    monthly_bill = float(custom.get("monthly_electric_bill", 150))

    print(f"📬 GHL webhook: contact={contact_id} address='{address}' bill=${monthly_bill}")

    # Enrich with Solar API
    solar_data = enrich_lead(address, monthly_bill)
    
    if "error" in solar_data:
        return JSONResponse({
            "status": "error",
            "contact_id": contact_id,
            "error": solar_data["error"]
        }, status_code=422)

    # Push back to GHL
    if contact_id:
        await update_ghl_contact(contact_id, solar_data)

    return JSONResponse({
        "status": "enriched",
        "contact_id": contact_id,
        "lead_grade": solar_data.get("lead_grade"),
        "priority": solar_data.get("priority"),
        "lead_score": solar_data.get("lead_score"),
        "annual_savings_yr1": solar_data.get("annual_savings_yr1_usd"),
        "system_kw": solar_data.get("system_size_kw"),
        "payback_years": solar_data.get("payback_years"),
    })


@app.get("/webhook/health")
async def health():
    return {"status": "ok", "ghl_connected": bool(GHL_API_KEY)}
