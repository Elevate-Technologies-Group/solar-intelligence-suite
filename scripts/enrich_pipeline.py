#!/usr/bin/env python3
"""
Pipeline Lead Enrichment Engine
Enriches all pipeline CRM leads that have missing solar data (lead_score=0)
with real Google Solar API data — updating the DB in-place.

CLI:
    python scripts/enrich_pipeline.py                  # enrich all unenriched leads
    python scripts/enrich_pipeline.py --all            # re-enrich ALL leads (force)
    python scripts/enrich_pipeline.py --id 3           # enrich single lead by ID
    python scripts/enrich_pipeline.py --id 3 --id 5   # multiple specific IDs
    python scripts/enrich_pipeline.py --dry-run        # show what would be enriched
    python scripts/enrich_pipeline.py --json           # JSON output
    python scripts/enrich_pipeline.py --workers 4      # parallel workers (default 3)

Importable:
    from scripts.enrich_pipeline import enrich_pipeline_leads
    result = enrich_pipeline_leads(force=False, workers=3)
"""

import sys, os, json, time, argparse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "/root/solar-tools")

# ── ANSI colors ───────────────────────────────────────────────────────────────
GREEN  = "\033[92m"; YELLOW = "\033[93m"; RED    = "\033[91m"
CYAN   = "\033[96m"; WHITE  = "\033[97m"; GRAY   = "\033[90m"
BOLD   = "\033[1m";  RESET  = "\033[0m";  BLUE   = "\033[94m"
MAGENTA= "\033[95m"

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "pipeline.db")


def get_db():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_leads_to_enrich(force: bool = False, lead_ids: list = None):
    """Return pipeline leads that need enrichment."""
    conn = get_db()
    try:
        if lead_ids:
            placeholders = ",".join("?" * len(lead_ids))
            rows = conn.execute(
                f"SELECT * FROM leads WHERE id IN ({placeholders}) ORDER BY id",
                lead_ids
            ).fetchall()
        elif force:
            rows = conn.execute("SELECT * FROM leads ORDER BY id").fetchall()
        else:
            # Only leads with no solar data (score=0 OR grade='N/A')
            rows = conn.execute(
                "SELECT * FROM leads WHERE lead_score = 0 OR lead_grade = 'N/A' ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_lead_solar_data(lead_id: int, solar_data: dict, monthly_bill: float = 0):
    """Write enrichment results back to the pipeline DB."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE leads SET
                lead_score  = ?,
                lead_grade  = ?,
                priority    = ?,
                sun_hours   = ?,
                system_size = ?,
                yr1_savings = ?,
                payback_yrs = ?,
                itc_savings = ?,
                cache_key   = ?,
                monthly_bill = CASE WHEN monthly_bill = 0 THEN ? ELSE monthly_bill END,
                updated_at  = ?
            WHERE id = ?
        """, (
            solar_data.get("lead_score", 0),
            solar_data.get("lead_grade", "N/A"),
            solar_data.get("priority", "UNKNOWN"),
            solar_data.get("sunshine_hours_per_year", 0),
            solar_data.get("system_size_kw", 0),
            solar_data.get("annual_savings_yr1_usd", 0),
            solar_data.get("payback_years", 0),
            solar_data.get("federal_itc_usd", 0),
            solar_data.get("cache_key", ""),
            monthly_bill,
            now,
            lead_id,
        ))
        conn.commit()
    finally:
        conn.close()


def enrich_one(lead: dict) -> dict:
    """Enrich a single pipeline lead. Returns result dict."""
    lead_id    = lead["id"]
    address    = lead["address"]
    bill       = lead["monthly_bill"] or 150.0
    contact    = lead.get("contact_name") or "Unknown"

    result = {
        "id": lead_id,
        "address": address,
        "contact": contact,
        "stage": lead["stage"],
        "success": False,
        "score": 0,
        "grade": "N/A",
        "priority": "UNKNOWN",
        "yr1_savings": 0,
        "payback_yrs": 0,
        "error": None,
    }

    try:
        from core.solar import enrich_lead
        solar = enrich_lead(address, monthly_bill=float(bill))

        if solar.get("error"):
            result["error"] = solar["error"]
            return result

        update_lead_solar_data(lead_id, solar, monthly_bill=float(bill))

        result.update({
            "success":    True,
            "score":      solar.get("lead_score", 0),
            "grade":      solar.get("lead_grade", "N/A"),
            "priority":   solar.get("priority", "UNKNOWN"),
            "yr1_savings": solar.get("annual_savings_yr1_usd", 0),
            "payback_yrs": solar.get("payback_years", 0),
            "itc":        solar.get("federal_itc_usd", 0),
            "sun_hours":  solar.get("sunshine_hours_per_year", 0),
            "system_kw":  solar.get("system_size_kw", 0),
            "cached":     solar.get("from_cache", False),
        })
    except Exception as e:
        result["error"] = str(e)

    return result


def enrich_pipeline_leads(
    force: bool = False,
    lead_ids: list = None,
    workers: int = 3,
    dry_run: bool = False,
    color: bool = True,
) -> dict:
    """
    Main enrichment function. Returns summary dict.
    """
    leads = fetch_leads_to_enrich(force=force, lead_ids=lead_ids)

    if not leads:
        return {
            "total": 0,
            "enriched": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
            "message": "No leads need enrichment (all already have solar data).",
        }

    if dry_run:
        return {
            "total": len(leads),
            "dry_run": True,
            "leads": [
                {"id": l["id"], "address": l["address"],
                 "contact": l.get("contact_name"), "stage": l["stage"]}
                for l in leads
            ],
            "message": f"Would enrich {len(leads)} lead(s).",
        }

    C = {"g": GREEN, "y": YELLOW, "r": RED, "c": CYAN, "b": BOLD, "x": RESET, "gray": GRAY} if color else {k: "" for k in ["g","y","r","c","b","x","gray"]}

    print(f"\n{C['c']}{C['b']}☀  PIPELINE LEAD ENRICHMENT ENGINE{C['x']}")
    print(f"{C['gray']}Enriching {len(leads)} pipeline lead(s) with real solar data...{C['x']}\n")

    results = []
    enriched = 0
    failed   = 0

    # Parallel enrichment
    with ThreadPoolExecutor(max_workers=min(workers, 5)) as ex:
        futures = {ex.submit(enrich_one, lead): lead for lead in leads}
        for future in as_completed(futures):
            r = future.result()
            results.append(r)

            if r["success"]:
                enriched += 1
                priority_color = C["g"] if r["priority"] in ("HOT",) else C["y"] if r["priority"] == "WARM" else C["gray"]
                cached_tag = f" {C['gray']}[cache]{C['x']}" if r.get("cached") else ""
                print(
                    f"  {C['g']}✓{C['x']} #{r['id']:>2}  "
                    f"{C['b']}{r['score']:>3}/100 {r['grade']:<3}{C['x']}  "
                    f"{priority_color}{r['priority']:<4}{C['x']}  "
                    f"${r['yr1_savings']:>7,.0f}/yr  "
                    f"{r['payback_yrs']:.1f}yr payback  "
                    f"{C['gray']}{r['address'][:45]}{C['x']}"
                    f"{cached_tag}"
                )
            else:
                failed += 1
                print(
                    f"  {C['r']}✗{C['x']} #{r['id']:>2}  "
                    f"{C['gray']}{r['address'][:45]}{C['x']}  "
                    f"{C['r']}ERROR: {r.get('error','unknown')}{C['x']}"
                )

    # Sort results by score desc
    results.sort(key=lambda r: r.get("score", 0), reverse=True)

    # Summary banner
    hot  = sum(1 for r in results if r.get("priority") == "HOT")
    warm = sum(1 for r in results if r.get("priority") == "WARM")
    total_pipeline = sum(r.get("yr1_savings", 0) * r.get("payback_yrs", 1) * 0.7 for r in results if r["success"])

    print(f"\n{C['c']}{'─'*65}{C['x']}")
    print(f"  {C['b']}ENRICHMENT COMPLETE{C['x']}  "
          f"{C['g']}{enriched} enriched{C['x']}  "
          f"{C['r']}{failed} failed{C['x']}")
    if enriched:
        avg_score = sum(r["score"] for r in results if r["success"]) / enriched
        avg_savings = sum(r["yr1_savings"] for r in results if r["success"]) / enriched
        print(f"  Avg score: {avg_score:.0f}/100  "
              f"HOT: {hot}  WARM: {warm}  "
              f"Avg yr1 savings: ${avg_savings:,.0f}")
    print(f"{C['c']}{'─'*65}{C['x']}\n")

    return {
        "total":    len(leads),
        "enriched": enriched,
        "failed":   failed,
        "hot":      hot,
        "warm":     warm,
        "results":  results,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Pipeline Lead Enrichment Engine — updates CRM leads with real solar data"
    )
    parser.add_argument("--all",      action="store_true", help="Re-enrich ALL leads (force)")
    parser.add_argument("--id",       type=int, action="append", dest="ids", metavar="N",
                        help="Enrich specific lead ID(s) — repeat for multiple")
    parser.add_argument("--dry-run",  action="store_true", help="Show what would be enriched, no writes")
    parser.add_argument("--workers",  type=int, default=3, help="Parallel workers (default 3, max 5)")
    parser.add_argument("--json",     action="store_true", help="Output JSON")
    parser.add_argument("--no-color", action="store_true", help="Plain text output")
    args = parser.parse_args()

    result = enrich_pipeline_leads(
        force    = args.all,
        lead_ids = args.ids,
        workers  = args.workers,
        dry_run  = args.dry_run,
        color    = not args.no_color,
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return

    if result["total"] == 0:
        print(f"\n✅ {result['message']}\n")
    elif args.dry_run:
        print(f"\n📋 DRY RUN — {result['message']}")
        for l in result.get("leads", []):
            print(f"   #{l['id']:>2}  {l['stage']:<12}  {l['address']}")


if __name__ == "__main__":
    main()
