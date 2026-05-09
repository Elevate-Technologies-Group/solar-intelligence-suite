#!/usr/bin/env python3
"""
GoHighLevel (GHL) Contact Push Integration
==========================================
Push enriched solar leads directly into GoHighLevel CRM as contacts.

Reads from environment:
    GHL_API_KEY      — Private Integration Token (required)
    GHL_LOCATION_ID  — Sub-account / location ID (required)
    GHL_PIPELINE_ID  — Optional: add contact to pipeline opportunity
    GHL_STAGE_ID     — Optional: pipeline stage for opportunity

If either GHL_API_KEY or GHL_LOCATION_ID is not set → graceful skip.

Usage (standalone):
    python integrations/ghl_push.py --address "1905 E Marquette Dr, Gilbert AZ" --bill 175
    python integrations/ghl_push.py --test-connection
    python integrations/ghl_push.py --help

Importable:
    from integrations.ghl_push import push_lead_to_ghl
    result = push_lead_to_ghl(lead, raw_address)
    # result: {pushed: True, contact_id: "xxx", ...}
    # or:     {skipped: True, reason: "..."}
    # or:     {pushed: False, error: "..."}
"""

import os, sys, json, argparse, re
from typing import Optional
sys.path.insert(0, "/root/solar-tools")

# ── Constants ─────────────────────────────────────────────────────────────────
GHL_API_BASE    = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2023-02-21"
SOURCE_TAG      = "solar-intelligence-suite"
DEFAULT_TAGS    = ["Solar Lead", "AI Scored"]

# ── ANSI colors ───────────────────────────────────────────────────────────────
GREEN  = "\033[92m"; YELLOW = "\033[93m"; RED    = "\033[91m"
CYAN   = "\033[96m"; WHITE  = "\033[97m"; GRAY   = "\033[90m"
BOLD   = "\033[1m";  RESET  = "\033[0m";  BLUE   = "\033[94m"
MAGENTA= "\033[95m"


def _get_creds() -> tuple[Optional[str], Optional[str]]:
    """Return (api_key, location_id) from env — either may be None."""
    return (
        os.environ.get("GHL_API_KEY"),
        os.environ.get("GHL_LOCATION_ID"),
    )


def _make_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
        "Version":       GHL_API_VERSION,
    }


def _parse_address(raw_address: str, lead: dict) -> dict:
    """Extract address components for GHL contact fields."""
    addr_info = {
        "address1": "",
        "city":     "",
        "state":    "",
        "postalCode": "",
        "country":  "US",
    }

    # Try formatted address from lead first
    formatted = lead.get("formatted_address", raw_address or "")

    # Parse pattern: "1905 E Marquette Dr, Gilbert, AZ 85234, USA"
    m = re.match(
        r'^([^,]+),\s*([^,]+),\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)',
        formatted.replace(", USA", "").replace(", US", "").strip()
    )
    if m:
        addr_info["address1"]   = m.group(1).strip()
        addr_info["city"]       = m.group(2).strip()
        addr_info["state"]      = m.group(3).strip()
        addr_info["postalCode"] = m.group(4).strip()
    else:
        # Fallback: just put full address in address1
        addr_info["address1"] = formatted.split(",")[0].strip() if formatted else raw_address

    return addr_info


def _build_tags(lead: dict) -> list[str]:
    """Build GHL contact tags from lead data."""
    tags = list(DEFAULT_TAGS)

    priority = lead.get("priority", "").upper()
    grade    = lead.get("grade", "")
    score    = lead.get("lead_score", 0)

    if priority in ("HOT", "WARM"):
        tags.append(f"Solar {priority.title()}")
    if grade:
        tags.append(f"Grade {grade}")
    if score >= 80:
        tags.append("High Value Solar")
    elif score >= 60:
        tags.append("Medium Value Solar")

    # Territory
    addr_parts = lead.get("formatted_address", "").split(",")
    if len(addr_parts) >= 3:
        city = addr_parts[-3].strip() if len(addr_parts) >= 3 else ""
        if city:
            tags.append(f"City: {city}")

    tags.append(SOURCE_TAG)
    return tags


def _build_custom_fields(lead: dict) -> list[dict]:
    """Build GHL custom field updates from lead data.
    
    Uses string key format — GHL supports key-based custom field updates.
    Common keys used by solar CRM setups.
    """
    fields = []

    def add(key: str, value):
        if value is not None and value != "" and value != 0:
            fields.append({"key": key, "field_value": str(value)})

    # Solar data
    add("solar_lead_score",         lead.get("lead_score"))
    add("solar_grade",              lead.get("grade"))
    add("solar_priority",           lead.get("priority"))
    add("solar_panels_recommended", lead.get("panels_recommended"))
    add("solar_system_size_kw",     lead.get("system_size_kw"))
    add("solar_annual_savings",     lead.get("annual_savings_yr1_usd"))
    add("solar_monthly_savings",    lead.get("monthly_savings_usd"))
    add("solar_net_cost",           lead.get("net_system_cost_usd"))
    add("solar_payback_years",      lead.get("payback_years"))
    add("solar_roi_25yr_pct",       lead.get("roi_25yr_pct"))
    add("solar_sunshine_hours",     lead.get("sunshine_hours_per_year"))
    add("solar_roof_segments",      lead.get("roof_segments"))
    add("solar_imagery_date",       lead.get("imagery_date"))
    add("solar_offset_pct",         lead.get("solar_offset_pct"))
    add("solar_co2_offset_kg",      lead.get("co2_offset_annual_kg"))

    # ITC
    itc = lead.get("federal_itc_usd")
    if itc:
        add("solar_federal_itc", f"${itc:,.0f}")

    return fields


def _build_note(lead: dict, raw_address: str) -> str:
    """Build a CRM note with full solar analysis summary."""
    score    = lead.get("lead_score", "N/A")
    grade    = lead.get("grade", "?")
    priority = lead.get("priority", "?")
    panels   = lead.get("panels_recommended", "?")
    kw       = lead.get("system_size_kw", "?")
    savings  = lead.get("annual_savings_yr1_usd", 0)
    monthly  = lead.get("monthly_savings_usd", 0)
    payback  = lead.get("payback_years", "?")
    roi      = lead.get("roi_25yr_pct", "?")
    net_cost = lead.get("net_system_cost_usd", 0)
    itc      = lead.get("federal_itc_usd", 0)
    sun      = lead.get("sunshine_hours_per_year", "?")

    pts_raw  = lead.get("talking_points", []) or []
    pts      = "\n".join(f"• {p}" for p in pts_raw[:3]) if pts_raw else "See analysis."

    note = f"""🌞 SOLAR INTELLIGENCE SUITE ANALYSIS
Generated by Solar Intelligence Suite (AI-powered lead scoring)

ADDRESS: {raw_address}
LEAD SCORE: {score}/100 — Grade {grade} ({priority})

SOLAR SYSTEM:
  • {panels} panels | {kw} kW system
  • {sun} sunshine hours/year
  • Federal ITC: ${itc:,.0f} (30% credit)

FINANCIALS:
  • Year 1 savings:  ${savings:,.0f}/yr  (${monthly:,.0f}/mo)
  • Net system cost: ${net_cost:,.0f} after ITC
  • Payback period:  {payback} years
  • 25-year ROI:     {roi}%

TOP TALKING POINTS:
{pts}

---
Scored by Solar Intelligence Suite | https://github.com/Elevate-Technologies-Group/solar-intelligence-suite"""
    return note


def push_lead_to_ghl(
    lead:        dict,
    raw_address: str  = "",
    *,
    first_name:  str  = "Solar",
    last_name:   str  = "Lead",
    email:       str  = "",
    phone:       str  = "",
    add_note:    bool = True,
    dry_run:     bool = False,
) -> dict:
    """
    Push an enriched lead to GoHighLevel as a contact.

    Args:
        lead:        Enriched lead dict from enrich_lead()
        raw_address: Original address string (used as fallback)
        first_name:  Contact first name (default: "Solar")
        last_name:   Contact last name (default: "Lead")
        email:       Contact email (optional)
        phone:       Contact phone (optional)
        add_note:    Add full solar analysis as a CRM note (default: True)
        dry_run:     If True, build payload but don't send (for testing)

    Returns:
        {pushed: True, contact_id: "xxx", action: "created"|"updated", url: ...}
        {skipped: True, reason: "..."}
        {pushed: False, error: "...", status_code: int}
    """
    api_key, location_id = _get_creds()

    if not api_key:
        return {"skipped": True, "reason": "GHL_API_KEY not set — skipping GHL push"}
    if not location_id:
        return {"skipped": True, "reason": "GHL_LOCATION_ID not set — skipping GHL push"}
    if lead.get("error"):
        return {"skipped": True, "reason": f"Lead has errors — not pushed: {lead['error']}"}

    # ── Build contact payload ──────────────────────────────────────────────────
    addr_fields  = _parse_address(raw_address or lead.get("formatted_address", ""), lead)
    tags         = _build_tags(lead)
    custom_fields = _build_custom_fields(lead)

    payload = {
        "locationId":   location_id,
        "firstName":    first_name,
        "lastName":     last_name,
        "address1":     addr_fields["address1"],
        "city":         addr_fields["city"],
        "state":        addr_fields["state"],
        "postalCode":   addr_fields["postalCode"],
        "country":      "US",
        "source":       SOURCE_TAG,
        "tags":         tags,
        "customFields": custom_fields,
    }
    if email:
        payload["email"] = email
    if phone:
        payload["phone"] = phone

    if dry_run:
        return {
            "dry_run":       True,
            "would_push_to": f"{GHL_API_BASE}/contacts/",
            "location_id":   location_id,
            "payload":       payload,
            "tags":          tags,
            "custom_fields": len(custom_fields),
        }

    # ── POST to GHL ───────────────────────────────────────────────────────────
    try:
        import urllib.request as urlreq
        import urllib.error

        data    = json.dumps(payload).encode("utf-8")
        req     = urlreq.Request(
            f"{GHL_API_BASE}/contacts/",
            data    = data,
            headers = _make_headers(api_key),
            method  = "POST",
        )

        with urlreq.urlopen(req, timeout=15) as resp:
            body       = json.loads(resp.read())
            contact_id = body.get("contact", {}).get("id") or body.get("id", "")
            contact    = body.get("contact", body)

        result = {
            "pushed":     True,
            "action":     "created",
            "contact_id": contact_id,
            "location_id": location_id,
            "url":        f"https://app.gohighlevel.com/contacts/{contact_id}",
            "name":       f"{first_name} {last_name}",
            "tags":       tags,
        }

        # ── Add note with full analysis ────────────────────────────────────────
        if add_note and contact_id:
            try:
                note_text = _build_note(lead, raw_address or lead.get("formatted_address", ""))
                note_payload = {
                    "userId":     "",
                    "contactId":  contact_id,
                    "body":       note_text,
                }
                note_data = json.dumps(note_payload).encode("utf-8")
                note_req  = urlreq.Request(
                    f"{GHL_API_BASE}/contacts/{contact_id}/notes/",
                    data    = note_data,
                    headers = _make_headers(api_key),
                    method  = "POST",
                )
                with urlreq.urlopen(note_req, timeout=10) as nr:
                    result["note_added"] = True
            except Exception as ne:
                result["note_error"] = str(ne)

        return result

    except Exception as e:
        err_body = ""
        if hasattr(e, "read"):
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
        status = getattr(e, "code", None)
        return {
            "pushed":      False,
            "error":       str(e),
            "error_body":  err_body,
            "status_code": status,
        }


def test_connection() -> dict:
    """Test GHL API connectivity without creating a contact."""
    api_key, location_id = _get_creds()
    if not api_key:
        return {"ok": False, "error": "GHL_API_KEY not set"}
    if not location_id:
        return {"ok": False, "error": "GHL_LOCATION_ID not set (set it to your sub-account ID)",
                "api_key_set": True}

    try:
        import urllib.request as urlreq
        req = urlreq.Request(
            f"{GHL_API_BASE}/contacts/?locationId={location_id}&limit=1",
            headers={**_make_headers(api_key), "Content-Type": "application/json"},
            method="GET",
        )
        with urlreq.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            count = body.get("meta", {}).get("total", "?")
            return {
                "ok":          True,
                "location_id": location_id,
                "contacts_in_crm": count,
                "message":     f"Connected! {count} contacts found in location.",
            }
    except Exception as e:
        err_body = ""
        if hasattr(e, "read"):
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
        return {
            "ok":          False,
            "error":       str(e),
            "error_body":  err_body,
            "status_code": getattr(e, "code", None),
        }


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Push solar lead to GoHighLevel CRM")
    parser.add_argument("address",         nargs="?",        help="Address to enrich and push")
    parser.add_argument("--bill",          type=float, default=175, help="Monthly electric bill")
    parser.add_argument("--name",          default="",         help="Homeowner name (first last)")
    parser.add_argument("--email",         default="",         help="Contact email")
    parser.add_argument("--phone",         default="",         help="Contact phone")
    parser.add_argument("--test-connection", action="store_true", help="Test GHL API connection")
    parser.add_argument("--dry-run",       action="store_true", help="Build payload, don't send")
    parser.add_argument("--no-color",      action="store_true", help="Disable ANSI colors")
    parser.add_argument("--json",          action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    if args.no_color:
        global GREEN, YELLOW, RED, CYAN, WHITE, GRAY, BOLD, RESET, BLUE, MAGENTA
        GREEN=YELLOW=RED=CYAN=WHITE=GRAY=BOLD=RESET=BLUE=MAGENTA=""

    if args.test_connection:
        result = test_connection()
        if args.json:
            print(json.dumps(result, indent=2))
            return
        if result.get("ok"):
            print(f"{GREEN}{BOLD}✅ GHL Connection OK{RESET}")
            print(f"   Location ID:  {result.get('location_id')}")
            print(f"   Contacts:     {result.get('contacts_in_crm')}")
        else:
            print(f"{RED}{BOLD}❌ GHL Connection Failed{RESET}")
            print(f"   Error:  {result.get('error')}")
            if result.get("api_key_set"):
                print(f"   {YELLOW}Hint: Set GHL_LOCATION_ID env var to your sub-account ID{RESET}")
        return

    if not args.address:
        parser.print_help()
        return

    # Enrich the lead
    print(f"{CYAN}{BOLD}🌞 Solar Intelligence Suite — GHL Push{RESET}")
    print(f"{GRAY}Address: {args.address}{RESET}")

    from core.solar import enrich_lead
    print(f"{GRAY}Enriching lead...{RESET}")
    lead = enrich_lead(args.address)

    if lead.get("error"):
        print(f"{RED}❌ Enrichment failed: {lead['error']}{RESET}")
        sys.exit(1)

    score    = lead.get("lead_score", 0)
    grade    = lead.get("grade", "?")
    priority = lead.get("priority", "?")
    savings  = lead.get("annual_savings_yr1_usd", 0)

    print(f"{GREEN}✅ Lead enriched — Score: {score}/100 | Grade: {grade} | {priority}{RESET}")
    print(f"   Savings: ${savings:,.0f}/yr | Payback: {lead.get('payback_years','?')} yrs")

    # Parse name
    first_name, last_name = "Solar", "Lead"
    if args.name:
        parts = args.name.strip().split(None, 1)
        first_name = parts[0]
        last_name  = parts[1] if len(parts) > 1 else "Lead"

    # Push to GHL
    print(f"\n{CYAN}Pushing to GoHighLevel...{RESET}")
    result = push_lead_to_ghl(
        lead,
        args.address,
        first_name=first_name,
        last_name=last_name,
        email=args.email,
        phone=args.phone,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if result.get("dry_run"):
        print(f"{YELLOW}{BOLD}🧪 DRY RUN — Payload built (not sent){RESET}")
        print(f"   Would POST to: {result['would_push_to']}")
        print(f"   Location ID:  {result['location_id']}")
        print(f"   Tags:         {', '.join(result['tags'])}")
        print(f"   Custom fields: {result['custom_fields']} fields")
    elif result.get("skipped"):
        print(f"{YELLOW}⚠️  Skipped: {result['reason']}{RESET}")
        print(f"\n   {GRAY}To enable GHL push:{RESET}")
        print(f"   {GRAY}export GHL_API_KEY=pit-...<your key>...{RESET}")
        print(f"   {GRAY}export GHL_LOCATION_ID=<your sub-account ID>{RESET}")
    elif result.get("pushed"):
        print(f"{GREEN}{BOLD}✅ Contact pushed to GHL!{RESET}")
        print(f"   Contact ID: {result.get('contact_id')}")
        print(f"   URL:        {result.get('url')}")
        print(f"   Tags:       {', '.join(result.get('tags', []))}")
        if result.get("note_added"):
            print(f"   {GREEN}📝 Full analysis note added to contact{RESET}")
    else:
        print(f"{RED}{BOLD}❌ Push failed{RESET}")
        print(f"   Error: {result.get('error')}")
        if result.get("error_body"):
            print(f"   Details: {result.get('error_body')}")


if __name__ == "__main__":
    main()
