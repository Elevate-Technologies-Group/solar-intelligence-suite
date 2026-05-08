#!/usr/bin/env python3
"""
batch_enrich.py — Batch solar lead enrichment from CSV → scored CSV

Reads a CSV of addresses, enriches each one via Google Solar API,
and outputs a scored CSV ready to import into GHL or any CRM.

Usage:
    python batch_enrich.py leads.csv
    python batch_enrich.py leads.csv --output scored_leads.csv
    python batch_enrich.py leads.csv --bill 200 --rate 0.155
    python batch_enrich.py leads.csv --workers 3

Input CSV format (headers optional, address must be first column):
    address[,monthly_bill][,utility_rate]

Example:
    1234 W Main St, Phoenix, AZ 85001
    5678 N 32nd St, Scottsdale, AZ 85251,225
    9012 E Camelback Rd, Tempe, AZ 85281,300,0.16
"""
import sys, os, csv, argparse, time, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Output columns (in order) ────────────────────────────────────────────────
OUTPUT_COLUMNS = [
    "address",
    "city",
    "state",
    "postal_code",
    "lead_grade",
    "priority",
    "lead_score",
    "monthly_bill_usd",
    "system_size_kw",
    "panels_recommended",
    "annual_kwh_produced",
    "offset_pct",
    "sunshine_hours_per_year",
    "roof_segments",
    "gross_cost_usd",
    "federal_itc_usd",
    "net_cost_usd",
    "annual_savings_yr1_usd",
    "payback_years",
    "roi_25yr_pct",
    "lifetime_savings_usd",
    "co2_offset_lbs_per_year",
    "trees_equivalent_per_year",
    "imagery_quality",
    "imagery_date",
    "error",
]

# ── Score breakdown columns (bonus detail columns) ───────────────────────────
SCORE_BREAKDOWN_COLS = ["score_sunshine", "score_roof", "score_bill", "score_payback", "score_roi"]


def parse_imagery_date(d):
    if isinstance(d, dict):
        y = d.get("year", "")
        m = d.get("month", "")
        return f"{y}-{m:02d}" if y else ""
    return str(d) if d else ""


def enrich_row(address: str, monthly_bill: float, utility_rate: float) -> dict:
    """Enrich a single address and return a flat dict for CSV output."""
    from core.solar import enrich_lead
    lead = enrich_lead(address, monthly_bill=monthly_bill, utility_rate=utility_rate)

    row = {col: "" for col in OUTPUT_COLUMNS + SCORE_BREAKDOWN_COLS}
    row["error"] = ""

    if "error" in lead:
        row["address"] = address
        row["monthly_bill_usd"] = monthly_bill
        row["error"] = lead["error"]
        return row

    for col in OUTPUT_COLUMNS:
        if col in lead:
            row[col] = lead[col]

    # Flatten imagery_date
    row["imagery_date"] = parse_imagery_date(lead.get("imagery_date", ""))

    # Flatten score breakdown
    bd = lead.get("score_breakdown", {})
    row["score_sunshine"] = bd.get("sunshine", "")
    row["score_roof"]     = bd.get("roof_quality", "")
    row["score_bill"]     = bd.get("monthly_bill", "")
    row["score_payback"]  = bd.get("payback", "")
    row["score_roi"]      = bd.get("roi", "")

    return row


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Batch solar lead enrichment — CSV in, scored CSV out",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input_csv", help="Input CSV file (addresses)")
    parser.add_argument("--output",  "-o", help="Output CSV path (default: <input>_scored.csv)")
    parser.add_argument("--bill",    "-b", type=float, default=175.0,
                        help="Default monthly bill USD if not in CSV (default: 175)")
    parser.add_argument("--rate",    "-r", type=float, default=0.14,
                        help="Default utility rate $/kWh (default: 0.14)")
    parser.add_argument("--workers", "-w", type=int, default=2,
                        help="Parallel workers (default: 2, max: 5)")
    parser.add_argument("--delay",   "-d", type=float, default=0.5,
                        help="Seconds between API calls per worker (default: 0.5)")
    args = parser.parse_args()

    # ── Validate input ───────────────────────────────────────────────────────
    if not os.path.exists(args.input_csv):
        print(f"ERROR: Input file not found: {args.input_csv}")
        sys.exit(1)

    workers = min(args.workers, 5)

    # ── Output path ──────────────────────────────────────────────────────────
    if args.output:
        output_path = args.output
    else:
        base = os.path.splitext(args.input_csv)[0]
        output_path = f"{base}_scored.csv"

    # ── Read input ───────────────────────────────────────────────────────────
    jobs = []  # list of (address, monthly_bill, utility_rate)
    with open(args.input_csv, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader, 1):
            if not row or not row[0].strip():
                continue
            address = row[0].strip()
            # Skip header row (first row with non-numeric first column that looks like a label)
            if i == 1 and address.lower() in ("address", "addresses", "street_address", "street"):
                continue
            # Also skip if second column is non-numeric and looks like a header
            col2 = row[1].strip() if len(row) > 1 else ""
            if i == 1 and col2 and not col2.replace(".", "").replace("-", "").isdigit():
                continue  # header row
            try:
                bill = float(col2) if col2 else args.bill
            except ValueError:
                bill = args.bill
            try:
                col3 = row[2].strip() if len(row) > 2 else ""
                rate = float(col3) if col3 else args.rate
            except ValueError:
                rate = args.rate
            jobs.append((address, bill, rate))

    if not jobs:
        print("ERROR: No addresses found in input CSV.")
        sys.exit(1)

    log(f"📋 Loaded {len(jobs)} addresses from {args.input_csv}")
    log(f"⚙️  Workers: {workers}  |  Delay: {args.delay}s  |  Default bill: ${args.bill:.0f}")
    log(f"💾 Output: {output_path}")
    print()

    # ── Run enrichment ───────────────────────────────────────────────────────
    results = []
    errors  = 0
    start   = time.time()

    def enrich_with_delay(job):
        addr, bill, rate = job
        result = enrich_row(addr, bill, rate)
        if args.delay > 0:
            time.sleep(args.delay)
        return result

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(enrich_with_delay, job): job for job in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            row = future.result()
            results.append(row)
            addr_short = (row.get("address") or futures[future][0])[:55]
            grade  = row.get("lead_grade", "?")
            score  = row.get("lead_score", "?")
            err    = row.get("error", "")
            if err:
                errors += 1
                log(f"  [{i:>3}/{len(jobs)}] ❌ {addr_short[:50]}... → ERROR: {err[:40]}")
            else:
                priority = row.get("priority", "")
                savings  = row.get("annual_savings_yr1_usd", 0)
                icon = "🔥" if priority == "HOT" else ("🌤" if priority == "WARM" else "❄️")
                log(f"  [{i:>3}/{len(jobs)}] {icon} [{grade}] {score}/100  ${savings:>6,.0f}/yr  {addr_short}")

    # ── Sort by lead score (descending) ─────────────────────────────────────
    results.sort(key=lambda r: (r.get("lead_score") or 0), reverse=True)

    # ── Write output CSV ─────────────────────────────────────────────────────
    all_cols = OUTPUT_COLUMNS + SCORE_BREAKDOWN_COLS
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    elapsed = time.time() - start
    hot   = sum(1 for r in results if r.get("priority") == "HOT")
    warm  = sum(1 for r in results if r.get("priority") == "WARM")
    avg_score = sum((r.get("lead_score") or 0) for r in results if not r.get("error")) / max(1, len(results) - errors)

    print()
    log(f"✅ Done in {elapsed:.1f}s")
    log(f"   Total processed : {len(jobs)}")
    log(f"   Successful       : {len(jobs) - errors}")
    log(f"   Errors           : {errors}")
    log(f"   🔥 HOT leads      : {hot}")
    log(f"   🌤  WARM leads     : {warm}")
    log(f"   Avg score         : {avg_score:.1f}/100")
    log(f"   Output saved to   : {output_path}")

    # ── Discord notification (if DISCORD_WEBHOOK_URL is set) ─────────────────
    try:
        from integrations.discord_alerts import notify_batch_results
        # Build full lead objects list for the notifier
        from core.solar import enrich_lead as _enrich_lead
        import json as _json
        # results are flat CSV dicts; reconstruct minimal lead objects
        lead_objects = []
        for r in results:
            if r.get("error"):
                continue
            lead_objects.append({
                "formatted_address": r.get("address", ""),
                "lead_grade":        r.get("lead_grade", ""),
                "priority":          r.get("priority", ""),
                "lead_score":        r.get("lead_score", 0),
                "monthly_bill_usd":  r.get("monthly_bill_usd", 0),
                "annual_savings_yr1_usd": r.get("annual_savings_yr1_usd", 0),
                "lifetime_savings_usd":   r.get("lifetime_savings_usd", 0),
                "net_cost_usd":       r.get("net_cost_usd", 0),
                "payback_years":      r.get("payback_years", 0),
                "system_size_kw":     r.get("system_size_kw", 0),
                "panels_recommended": r.get("panels_recommended", 0),
                "roof_segments":      r.get("roof_segments", 0),
                "sunshine_hours_per_year": r.get("sunshine_hours_per_year", 0),
                "imagery_date":       r.get("imagery_date", ""),
            })
        source_name = os.path.basename(args.input_csv)
        notify_batch_results(lead_objects, source_file=source_name, hot_only=False)
        if hot > 0:
            log(f"   📣 Discord alert sent ({hot} HOT leads)")
    except Exception as _e:
        pass  # Discord is optional — never crash the main script


if __name__ == "__main__":
    main()
