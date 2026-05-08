# Solar Intelligence Suite 🌞

**AI-powered solar lead enrichment, territory analysis, and proposal generation — built for solar sales teams.**

Built overnight by [Hermes AI](https://github.com/NousResearch/hermes-agent) using Google's Solar API, Maps Platform, and Places API.

---

## What This Does

Every time a lead comes in from your dialer, before your rep picks up the phone, this system:

1. **Geocodes** the address → precise lat/lng
2. **Hits Google Solar API** → analyzes the actual roof via satellite
3. **Calculates financials** → savings, payback, 25-year ROI, federal ITC
4. **Scores the lead** → 0–100 score, A+/A/B/C/D grade, HOT/WARM/COOL priority
5. **Generates talking points** → address-specific pitch points for your rep
6. **Returns everything in <2 seconds** (cached after first lookup)

---

## Stack

- **Google Solar API** — rooftop solar potential analysis
- **Google Geocoding API** — address → lat/lng
- **Google Places API** — territory residential discovery  
- **Google Maps Static API** — aerial roof imagery
- **FastAPI** — REST API backend
- **Pure Python** — no heavy ML dependencies

---

## Quick Start

```bash
git clone https://github.com/Elevate-Technologies-Group/solar-intelligence-suite
cd solar-intelligence-suite

# Set your API key
export GOOGLE_MAPS_API_KEY=your_key_here

# Install deps
pip install fastapi uvicorn requests httpx pydantic

# Start the server
python3 -m uvicorn api:app --host 0.0.0.0 --port 8765

# Open dashboard
open http://localhost:8765
```

---

## API Endpoints

### Enrich a Lead
```bash
curl "http://localhost:8765/api/lead/enrich?address=123+Main+St,+Phoenix,+AZ+85001&monthly_bill=200"
```

Response:
```json
{
  "address": "123 Main St, Phoenix, AZ 85001",
  "lead_score": 87,
  "lead_grade": "A+",
  "priority": "HOT",
  "system_size_kw": 9.2,
  "panels_recommended": 23,
  "annual_savings_yr1_usd": 2840,
  "net_cost_usd": 19320,
  "payback_years": 6.8,
  "roi_25yr_pct": 287,
  "lifetime_savings_usd": 104320,
  "sunshine_hours_per_year": 2310,
  "talking_points": [
    "✅ Your roof gets 2,310 hours of sunshine per year...",
    "💰 You'd save roughly $2,840 in year one alone...",
    ...
  ]
}
```

### Scan a Territory
```bash
curl -X POST http://localhost:8765/api/territory/scan \
  -H "Content-Type: application/json" \
  -d '{"zip_code": "85234", "sample_size": 8, "avg_monthly_bill": 175}'
```

### Generate a Proposal
```bash
curl "http://localhost:8765/api/proposal/123+Main+St,+Phoenix,+AZ?customer_name=John+Smith&monthly_bill=200"
```

---

## GHL Integration

See [`integrations/ghl_webhook.py`](integrations/ghl_webhook.py) for the GoHighLevel webhook handler.

Set up in GHL: **Automations → Trigger: Contact Created → Action: Webhook → POST to your server**

When a lead is created in GHL:
- Solar analysis runs automatically
- Contact custom fields populated with solar data
- Tagged as `solar-hot`, `solar-warm`, or `solar-cool`
- Note added with rep talking points

---

## Supabase Schema

See [`integrations/supabase_schema.py`](integrations/supabase_schema.py) for the full database schema including:
- `solar_leads` table with all enrichment data
- `territory_scans` table for cached zip code analysis
- `proposals` table for tracking sent proposals
- `hot_leads_dashboard` view for reps
- `territory_performance` view for sales managers

---

## Lead Scoring System

| Factor | Max Points | What It Measures |
|--------|-----------|-----------------|
| Sunshine hours | 25 | Annual solar irradiance at this address |
| Roof quality | 15 | Number of usable roof segments |
| Monthly bill | 30 | Higher bill = better solar candidate |
| Payback period | 20 | Shorter payback = easier sell |
| 25-year ROI | 10 | Long-term return on investment |

**Grades:** A+ (80-100) · A (65-79) · B (50-64) · C (35-49) · D (<35)

---

## Project Structure

```
solar-intelligence-suite/
├── api.py                    # FastAPI backend (all REST endpoints)
├── core/
│   ├── config.py             # API keys, defaults, constants
│   └── solar.py              # Solar API wrapper + financial calculations
├── tools/
│   └── territory.py          # Territory scanner + zip code analysis
├── integrations/
│   ├── ghl_webhook.py        # GoHighLevel webhook handler
│   └── supabase_schema.py    # Database schema SQL
├── web/
│   └── dashboard.html        # Single-page dashboard UI
└── cache/                    # Disk cache for API responses
```

---

## Cost Estimates

| API | Cost | Notes |
|-----|------|-------|
| Solar API | $3/1000 calls | Cached after first lookup |
| Geocoding | $5/1000 calls | Cached after first lookup |
| Places API | $32/1000 calls | Territory scan only |
| Maps Static | $2/1000 calls | Dashboard aerial imagery |

**Typical cost per lead enrichment: ~$0.008** (less than 1 cent)

---

*Built by Hermes AI for Elevate Technologies Group*
