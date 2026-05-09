#!/usr/bin/env python3
"""
Solar Lead Pipeline CRM
SQLite-backed lead status tracker — move leads through the full sales funnel.

Stages: new → contacted → qualified → proposed → closed_won / closed_lost

CLI Usage:
    python scripts/pipeline.py list                          # show all leads
    python scripts/pipeline.py list --stage qualified        # filter by stage
    python scripts/pipeline.py add "123 Main St, Phoenix AZ" --bill 185 --name "John Smith" --phone "480-555-1234"
    python scripts/pipeline.py move <lead_id> contacted      # advance stage
    python scripts/pipeline.py note <lead_id> "Called, left VM"
    python scripts/pipeline.py show <lead_id>                # full lead detail
    python scripts/pipeline.py stats                         # pipeline summary
    python scripts/pipeline.py import-cache                  # import enriched cache leads

Importable:
    from scripts.pipeline import PipelineCRM
    crm = PipelineCRM()
    lead_id = crm.add_lead(address="...", contact_name="...", monthly_bill=175)
    crm.move_stage(lead_id, "contacted")
    crm.add_note(lead_id, "Left voicemail")
"""

import sys, os, json, sqlite3, argparse, textwrap
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/root/solar-tools")

# ── ANSI colors ───────────────────────────────────────────────────────────────
GREEN   = "\033[92m"; YELLOW  = "\033[93m"; RED     = "\033[91m"
CYAN    = "\033[96m"; WHITE   = "\033[97m"; GRAY    = "\033[90m"
BOLD    = "\033[1m";  RESET   = "\033[0m";  BLUE    = "\033[94m"
MAGENTA = "\033[95m"; DIM     = "\033[2m"

# ── Stage config ──────────────────────────────────────────────────────────────
STAGES = ["new", "contacted", "qualified", "proposed", "closed_won", "closed_lost"]
STAGE_COLORS = {
    "new":          CYAN,
    "contacted":    BLUE,
    "qualified":    YELLOW,
    "proposed":     MAGENTA,
    "closed_won":   GREEN,
    "closed_lost":  RED,
}
STAGE_ICONS = {
    "new":          "🆕",
    "contacted":    "📞",
    "qualified":    "⚡",
    "proposed":     "📋",
    "closed_won":   "✅",
    "closed_lost":  "❌",
}
STAGE_LABELS = {
    "new":          "New Lead",
    "contacted":    "Contacted",
    "qualified":    "Qualified",
    "proposed":     "Proposed",
    "closed_won":   "Closed Won",
    "closed_lost":  "Closed Lost",
}

DB_PATH = Path("/root/solar-tools/cache/pipeline.db")


class PipelineCRM:
    """SQLite-backed solar lead pipeline."""

    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                address     TEXT NOT NULL,
                contact_name TEXT,
                phone       TEXT,
                email       TEXT,
                monthly_bill REAL DEFAULT 0,
                stage       TEXT DEFAULT 'new',
                lead_score  INTEGER DEFAULT 0,
                lead_grade  TEXT DEFAULT 'N/A',
                priority    TEXT DEFAULT 'UNKNOWN',
                sun_hours   REAL DEFAULT 0,
                system_size REAL DEFAULT 0,
                yr1_savings REAL DEFAULT 0,
                payback_yrs REAL DEFAULT 0,
                itc_savings REAL DEFAULT 0,
                source      TEXT DEFAULT 'manual',
                cache_key   TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now')),
                closed_at   TEXT,
                deal_value  REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS notes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id    INTEGER NOT NULL,
                note       TEXT NOT NULL,
                author     TEXT DEFAULT 'rep',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            );

            CREATE TABLE IF NOT EXISTS stage_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id    INTEGER NOT NULL,
                from_stage TEXT,
                to_stage   TEXT NOT NULL,
                changed_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (lead_id) REFERENCES leads(id)
            );
        """)
        self.conn.commit()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add_lead(self, address: str, contact_name: str = "", phone: str = "",
                 email: str = "", monthly_bill: float = 0, source: str = "manual",
                 enrich: bool = True, cache_key: str = "") -> int:
        """Add a lead, optionally enriching it via the Solar API."""
        solar_data = {}
        if enrich and address:
            try:
                from core.solar import enrich_lead
                solar_data = enrich_lead(address, monthly_bill=monthly_bill or 150)
            except Exception as e:
                print(f"{YELLOW}⚠ Could not enrich: {e}{RESET}")

        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO leads
                (address, contact_name, phone, email, monthly_bill, stage,
                 lead_score, lead_grade, priority, sun_hours, system_size,
                 yr1_savings, payback_yrs, itc_savings, source, cache_key)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            address, contact_name, phone, email,
            monthly_bill or solar_data.get("monthly_bill_usd", 0),
            "new",
            solar_data.get("lead_score", 0),
            solar_data.get("lead_grade", "N/A"),
            solar_data.get("priority", "UNKNOWN"),
            solar_data.get("sunshine_hours_per_year", 0),
            solar_data.get("system_size_kw", 0),
            solar_data.get("annual_savings_yr1_usd", 0),
            solar_data.get("payback_years", 0),
            solar_data.get("federal_itc_usd", 0),
            source,
            cache_key or solar_data.get("cache_key", ""),
        ))
        self.conn.commit()
        lead_id = cur.lastrowid
        # Record initial stage
        cur.execute("INSERT INTO stage_history (lead_id, from_stage, to_stage) VALUES (?,?,?)",
                    (lead_id, None, "new"))
        self.conn.commit()
        return lead_id

    def get_lead(self, lead_id: int) -> dict | None:
        cur = self.conn.cursor()
        row = cur.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        notes = cur.execute(
            "SELECT * FROM notes WHERE lead_id=? ORDER BY created_at DESC", (lead_id,)
        ).fetchall()
        d["notes"] = [dict(n) for n in notes]
        history = cur.execute(
            "SELECT * FROM stage_history WHERE lead_id=? ORDER BY changed_at", (lead_id,)
        ).fetchall()
        d["stage_history"] = [dict(h) for h in history]
        return d

    def list_leads(self, stage: str = None, limit: int = 100) -> list[dict]:
        cur = self.conn.cursor()
        if stage:
            rows = cur.execute(
                "SELECT * FROM leads WHERE stage=? ORDER BY lead_score DESC, created_at DESC LIMIT ?",
                (stage, limit)
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT * FROM leads ORDER BY stage, lead_score DESC, created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def move_stage(self, lead_id: int, new_stage: str) -> bool:
        if new_stage not in STAGES:
            return False
        cur = self.conn.cursor()
        row = cur.execute("SELECT stage FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not row:
            return False
        old_stage = row["stage"]
        now = datetime.now(timezone.utc).isoformat()
        closed_at = now if new_stage in ("closed_won", "closed_lost") else None
        cur.execute(
            "UPDATE leads SET stage=?, updated_at=?, closed_at=? WHERE id=?",
            (new_stage, now, closed_at, lead_id)
        )
        cur.execute(
            "INSERT INTO stage_history (lead_id, from_stage, to_stage) VALUES (?,?,?)",
            (lead_id, old_stage, new_stage)
        )
        self.conn.commit()
        return True

    def add_note(self, lead_id: int, note: str, author: str = "rep") -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO notes (lead_id, note, author) VALUES (?,?,?)",
            (lead_id, note, author)
        )
        cur.execute("UPDATE leads SET updated_at=datetime('now') WHERE id=?", (lead_id,))
        self.conn.commit()
        return True

    def set_deal_value(self, lead_id: int, value: float) -> bool:
        cur = self.conn.cursor()
        cur.execute("UPDATE leads SET deal_value=?, updated_at=datetime('now') WHERE id=?",
                    (value, lead_id))
        self.conn.commit()
        return True

    def stats(self) -> dict:
        cur = self.conn.cursor()
        rows = cur.execute("""
            SELECT stage,
                   COUNT(*) as count,
                   AVG(lead_score) as avg_score,
                   SUM(deal_value) as pipeline_value,
                   SUM(CASE WHEN priority='HOT' THEN 1 ELSE 0 END) as hot_count
            FROM leads GROUP BY stage
        """).fetchall()
        by_stage = {r["stage"]: dict(r) for r in rows}
        total = cur.execute("SELECT COUNT(*) as n FROM leads").fetchone()["n"]
        won_val = cur.execute(
            "SELECT SUM(deal_value) as v FROM leads WHERE stage='closed_won'"
        ).fetchone()["v"] or 0
        pipeline_val = cur.execute(
            "SELECT SUM(deal_value) as v FROM leads WHERE stage NOT IN ('closed_won','closed_lost')"
        ).fetchone()["v"] or 0
        return {
            "total_leads": total,
            "by_stage": by_stage,
            "closed_won_revenue": won_val,
            "active_pipeline_value": pipeline_val,
        }

    def import_from_cache(self, max_leads: int = 20) -> int:
        """Scan cache JSON files and import hot leads not already in the pipeline."""
        cache_dir = Path("/root/solar-tools/cache")
        cur = self.conn.cursor()
        existing_keys = {
            r[0] for r in cur.execute("SELECT cache_key FROM leads WHERE cache_key IS NOT NULL")
        }
        imported = 0
        for json_file in sorted(cache_dir.glob("*.json"))[:80]:
            if imported >= max_leads:
                break
            try:
                with open(json_file) as f:
                    data = json.load(f)
                if not isinstance(data, dict) or "lead_score" not in data:
                    continue
                key = json_file.stem
                if key in existing_keys:
                    continue
                if data.get("lead_score", 0) < 50:
                    continue  # skip low-quality leads
                address = data.get("address", "")
                if not address:
                    continue
                cur.execute("""
                    INSERT INTO leads
                        (address, monthly_bill, stage, lead_score, lead_grade, priority,
                         sun_hours, system_size, yr1_savings, payback_yrs, itc_savings,
                         source, cache_key)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    address,
                    data.get("monthly_bill_usd", 0),
                    "new",
                    data.get("lead_score", 0),
                    data.get("lead_grade", "N/A"),
                    data.get("priority", "UNKNOWN"),
                    data.get("sunshine_hours_per_year", 0),
                    data.get("system_size_kw", 0),
                    data.get("annual_savings_yr1_usd", 0),
                    data.get("payback_years", 0),
                    data.get("federal_itc_usd", 0),
                    "cache",
                    key,
                ))
                existing_keys.add(key)
                imported += 1
            except Exception:
                continue
        self.conn.commit()
        return imported


# ── CLI rendering ─────────────────────────────────────────────────────────────

def render_pipeline_board(leads: list[dict]):
    """Print a compact Kanban-style pipeline board."""
    by_stage = {s: [] for s in STAGES}
    for lead in leads:
        stage = lead.get("stage", "new")
        if stage in by_stage:
            by_stage[stage].append(lead)

    print(f"\n{BOLD}{WHITE}{'═'*72}{RESET}")
    print(f"{BOLD}{YELLOW}  ☀  SOLAR LEAD PIPELINE  {GRAY}— {len(leads)} total leads{RESET}")
    print(f"{BOLD}{WHITE}{'═'*72}{RESET}\n")

    for stage in STAGES:
        items = by_stage[stage]
        col = STAGE_COLORS[stage]
        icon = STAGE_ICONS[stage]
        label = STAGE_LABELS[stage]
        hot_count = sum(1 for l in items if l.get("priority") == "HOT")
        print(f"{col}{BOLD}  {icon} {label.upper()}{RESET} {GRAY}({len(items)} leads{', ' + str(hot_count) + ' 🔥' if hot_count else ''}){RESET}")
        if not items:
            print(f"    {GRAY}— empty —{RESET}")
        for lead in items[:5]:
            score = lead.get("lead_score", 0)
            grade = lead.get("lead_grade", "?")
            prio  = lead.get("priority", "")
            addr  = lead.get("address", "Unknown")[:42]
            name  = lead.get("contact_name") or ""
            bill  = lead.get("monthly_bill", 0)
            did   = lead.get("id", "?")
            prio_icon = "🔥" if prio == "HOT" else "🌤" if prio == "WARM" else "❄"
            score_color = GREEN if score >= 75 else YELLOW if score >= 50 else RED
            bill_str = f"${bill:.0f}/mo" if bill else ""
            name_str = f"  {CYAN}{name}{RESET}" if name else ""
            print(f"    {GRAY}#{did:>3}{RESET}  {score_color}{score:>3}/100 {grade}{RESET}  {prio_icon}  {WHITE}{addr}{RESET}{name_str}  {GRAY}{bill_str}{RESET}")
        if len(items) > 5:
            print(f"    {GRAY}  … and {len(items)-5} more{RESET}")
        print()


def render_lead_detail(lead: dict):
    """Print full lead detail."""
    col   = STAGE_COLORS.get(lead.get("stage", "new"), WHITE)
    icon  = STAGE_ICONS.get(lead.get("stage", "new"), "?")
    score = lead.get("lead_score", 0)
    score_color = GREEN if score >= 75 else YELLOW if score >= 50 else RED

    print(f"\n{BOLD}{WHITE}{'═'*64}{RESET}")
    print(f"{BOLD}{YELLOW}  ☀  LEAD #{lead['id']} — {lead['address']}{RESET}")
    print(f"{BOLD}{WHITE}{'═'*64}{RESET}")
    print(f"  Stage:    {col}{BOLD}{icon} {STAGE_LABELS[lead['stage']]}{RESET}")
    print(f"  Score:    {score_color}{BOLD}{score}/100 {lead.get('lead_grade','?')} — {lead.get('priority','?')}{RESET}")
    if lead.get("contact_name"):
        print(f"  Contact:  {WHITE}{lead['contact_name']}{RESET}  {CYAN}{lead.get('phone','')}{RESET}  {GRAY}{lead.get('email','')}{RESET}")
    if lead.get("monthly_bill"):
        print(f"  Avg Bill: {WHITE}${lead['monthly_bill']:.0f}/mo{RESET}")
    print()
    print(f"  {BOLD}Solar Data:{RESET}")
    print(f"    Sun Hours:   {lead.get('sun_hours',0):.0f} kWh/yr")
    print(f"    System Size: {lead.get('system_size',0):.1f} kW")
    print(f"    Yr1 Savings: ${lead.get('yr1_savings',0):,.0f}")
    print(f"    Payback:     {lead.get('payback_yrs',0):.1f} years")
    print(f"    ITC Credit:  ${lead.get('itc_savings',0):,.0f}")
    if lead.get("deal_value"):
        print(f"    Deal Value:  {GREEN}${lead['deal_value']:,.0f}{RESET}")
    print()

    # Stage history
    if lead.get("stage_history"):
        print(f"  {BOLD}Stage History:{RESET}")
        for h in lead["stage_history"]:
            ts = h["changed_at"][:16]
            frm = h["from_stage"] or "—"
            print(f"    {GRAY}{ts}{RESET}  {frm} → {STAGE_COLORS.get(h['to_stage'],WHITE)}{h['to_stage']}{RESET}")
        print()

    # Notes
    if lead.get("notes"):
        print(f"  {BOLD}Notes ({len(lead['notes'])}):{RESET}")
        for n in lead["notes"]:
            ts = n["created_at"][:16]
            print(f"    {GRAY}{ts} [{n['author']}]{RESET}  {n['note']}")
    else:
        print(f"  {GRAY}No notes yet. Add with: pipeline.py note {lead['id']} \"message\"{RESET}")
    print(f"\n{BOLD}{WHITE}{'═'*64}{RESET}\n")


def render_stats(stats: dict):
    """Print pipeline summary stats."""
    print(f"\n{BOLD}{WHITE}{'═'*60}{RESET}")
    print(f"{BOLD}{YELLOW}  ☀  PIPELINE STATS{RESET}")
    print(f"{BOLD}{WHITE}{'═'*60}{RESET}\n")

    total = stats["total_leads"]
    print(f"  Total Leads:        {WHITE}{BOLD}{total}{RESET}")
    print(f"  Won Revenue:        {GREEN}{BOLD}${stats['closed_won_revenue']:,.0f}{RESET}")
    print(f"  Active Pipeline:    {CYAN}{BOLD}${stats['active_pipeline_value']:,.0f}{RESET}")
    print()

    stage_order = STAGES
    for stage in stage_order:
        s = stats["by_stage"].get(stage, {})
        if not s:
            continue
        col   = STAGE_COLORS[stage]
        icon  = STAGE_ICONS[stage]
        label = STAGE_LABELS[stage]
        count = s.get("count", 0)
        avg   = s.get("avg_score") or 0
        hot   = s.get("hot_count", 0)
        val   = s.get("pipeline_value") or 0
        bar   = "█" * min(count, 20)
        print(f"  {col}{icon} {label:<14}{RESET}  {bar:<20}  {WHITE}{count:>3}{RESET} leads  "
              f"{GRAY}avg {avg:.0f}/100{RESET}"
              + (f"  {RED}🔥×{hot}{RESET}" if hot else "")
              + (f"  {GREEN}${val:,.0f}{RESET}" if val else ""))
    print(f"\n{BOLD}{WHITE}{'═'*60}{RESET}\n")


# ── Main CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Solar Lead Pipeline CRM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python scripts/pipeline.py list
          python scripts/pipeline.py list --stage qualified
          python scripts/pipeline.py add "123 Main St, Gilbert AZ" --bill 185 --name "John Smith" --phone "480-555-1234"
          python scripts/pipeline.py move 3 contacted
          python scripts/pipeline.py note 3 "Called — interested, call back Thursday"
          python scripts/pipeline.py show 3
          python scripts/pipeline.py stats
          python scripts/pipeline.py import-cache
        """)
    )
    sub = parser.add_subparsers(dest="cmd")

    # list
    p_list = sub.add_parser("list", help="List all leads")
    p_list.add_argument("--stage", choices=STAGES, help="Filter by stage")
    p_list.add_argument("--limit", type=int, default=100)

    # add
    p_add = sub.add_parser("add", help="Add a new lead")
    p_add.add_argument("address", help="Property address")
    p_add.add_argument("--bill", type=float, default=0, help="Monthly bill $")
    p_add.add_argument("--name", default="", help="Contact name")
    p_add.add_argument("--phone", default="", help="Phone number")
    p_add.add_argument("--email", default="", help="Email")
    p_add.add_argument("--no-enrich", action="store_true", help="Skip Solar API enrichment")

    # move
    p_move = sub.add_parser("move", help="Move lead to a new stage")
    p_move.add_argument("lead_id", type=int)
    p_move.add_argument("stage", choices=STAGES)

    # note
    p_note = sub.add_parser("note", help="Add a note to a lead")
    p_note.add_argument("lead_id", type=int)
    p_note.add_argument("text", help="Note text")
    p_note.add_argument("--author", default="rep")

    # show
    p_show = sub.add_parser("show", help="Show full lead detail")
    p_show.add_argument("lead_id", type=int)

    # stats
    sub.add_parser("stats", help="Pipeline summary statistics")

    # import-cache
    p_import = sub.add_parser("import-cache", help="Import enriched leads from cache")
    p_import.add_argument("--max", type=int, default=20)

    # deal
    p_deal = sub.add_parser("deal", help="Set deal value for a lead")
    p_deal.add_argument("lead_id", type=int)
    p_deal.add_argument("value", type=float, help="Deal value in $")

    args = parser.parse_args()
    crm = PipelineCRM()

    if args.cmd == "list":
        leads = crm.list_leads(stage=args.stage, limit=args.limit)
        render_pipeline_board(leads)

    elif args.cmd == "add":
        print(f"{CYAN}Adding lead: {args.address}{RESET}")
        if not args.no_enrich:
            print(f"{GRAY}Enriching via Solar API (uses cache)…{RESET}")
        lead_id = crm.add_lead(
            address=args.address,
            contact_name=args.name,
            phone=args.phone,
            email=args.email,
            monthly_bill=args.bill,
            enrich=not args.no_enrich,
        )
        print(f"{GREEN}✓ Lead #{lead_id} added!{RESET}")
        lead = crm.get_lead(lead_id)
        if lead:
            render_lead_detail(lead)

    elif args.cmd == "move":
        ok = crm.move_stage(args.lead_id, args.stage)
        if ok:
            col = STAGE_COLORS[args.stage]
            print(f"{GREEN}✓ Lead #{args.lead_id} moved to {col}{STAGE_ICONS[args.stage]} {STAGE_LABELS[args.stage]}{RESET}")
        else:
            print(f"{RED}✗ Lead #{args.lead_id} not found or invalid stage.{RESET}")
            sys.exit(1)

    elif args.cmd == "note":
        ok = crm.add_note(args.lead_id, args.text, args.author)
        if ok:
            print(f"{GREEN}✓ Note added to lead #{args.lead_id}{RESET}")
        else:
            print(f"{RED}✗ Lead #{args.lead_id} not found.{RESET}")
            sys.exit(1)

    elif args.cmd == "show":
        lead = crm.get_lead(args.lead_id)
        if lead:
            render_lead_detail(lead)
        else:
            print(f"{RED}✗ Lead #{args.lead_id} not found.{RESET}")
            sys.exit(1)

    elif args.cmd == "stats":
        render_stats(crm.stats())

    elif args.cmd == "import-cache":
        print(f"{CYAN}Scanning cache for enriched leads…{RESET}")
        n = crm.import_from_cache(max_leads=args.max)
        print(f"{GREEN}✓ Imported {n} leads from cache.{RESET}")
        render_stats(crm.stats())

    elif args.cmd == "deal":
        ok = crm.set_deal_value(args.lead_id, args.value)
        if ok:
            print(f"{GREEN}✓ Deal value for lead #{args.lead_id} set to ${args.value:,.0f}{RESET}")
        else:
            print(f"{RED}✗ Lead #{args.lead_id} not found.{RESET}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
