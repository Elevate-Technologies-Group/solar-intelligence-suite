"""
Supabase schema for Solar Intelligence Suite.
Run these SQL commands in your Supabase SQL editor to set up the database.
"""

SCHEMA_SQL = """
-- ============================================================
-- Solar Intelligence Suite — Supabase Schema
-- ============================================================

-- Enable UUID extension
create extension if not exists "uuid-ossp";


-- ────────────────────────────────────────────────────────────
-- solar_leads: enriched lead records
-- ────────────────────────────────────────────────────────────
create table if not exists solar_leads (
  id              uuid primary key default uuid_generate_v4(),
  created_at      timestamp with time zone default now(),
  updated_at      timestamp with time zone default now(),

  -- Address data
  raw_address     text not null,
  formatted_address text,
  lat             numeric(10,7),
  lng             numeric(10,7),
  city            text,
  state           text,
  postal_code     text,
  place_id        text,

  -- CRM integration
  ghl_contact_id  text unique,
  rep_id          text,

  -- Solar potential
  sunshine_hours_per_year integer,
  roof_segments   integer,
  max_panels_possible integer,
  panels_recommended integer,
  system_size_kw  numeric(6,2),
  annual_kwh_produced integer,
  annual_kwh_needed integer,
  energy_offset_pct integer,
  imagery_quality text,

  -- Financials
  monthly_bill_usd numeric(8,2),
  utility_rate     numeric(6,4),
  gross_cost_usd   numeric(10,0),
  federal_itc_usd  numeric(10,0),
  net_cost_usd     numeric(10,0),
  annual_savings_yr1_usd numeric(8,0),
  lifetime_savings_usd numeric(12,0),
  payback_years    numeric(5,1),
  roi_25yr_pct     numeric(6,1),
  co2_offset_lbs_per_year numeric(10,0),

  -- Lead scoring
  lead_score      integer,
  lead_grade      text,
  priority        text check (priority in ('HOT', 'WARM', 'COOL', 'LOW')),
  score_breakdown jsonb,

  -- Talking points & raw data
  talking_points  jsonb,
  raw_solar_data  jsonb,

  -- Pipeline tracking
  status          text default 'new' check (status in ('new','contacted','quoted','closed_won','closed_lost','dnq')),
  notes           text
);

-- Indexes for common queries
create index if not exists idx_solar_leads_postal_code on solar_leads(postal_code);
create index if not exists idx_solar_leads_priority on solar_leads(priority);
create index if not exists idx_solar_leads_lead_score on solar_leads(lead_score desc);
create index if not exists idx_solar_leads_ghl_contact on solar_leads(ghl_contact_id);
create index if not exists idx_solar_leads_state on solar_leads(state);
create index if not exists idx_solar_leads_status on solar_leads(status);


-- ────────────────────────────────────────────────────────────
-- territory_scans: cached territory analysis results
-- ────────────────────────────────────────────────────────────
create table if not exists territory_scans (
  id              uuid primary key default uuid_generate_v4(),
  scanned_at      timestamp with time zone default now(),

  zip_code        text not null,
  center_address  text,
  lat             numeric(10,7),
  lng             numeric(10,7),

  addresses_scanned integer,
  leads_enriched  integer,
  hot_leads       integer,
  avg_lead_score  numeric(5,1),
  avg_annual_savings_usd numeric(8,0),
  avg_payback_years numeric(5,1),
  territory_grade text check (territory_grade in ('HOT', 'WARM', 'COOL')),

  raw_results     jsonb
);

create index if not exists idx_territory_scans_zip on territory_scans(zip_code);
create index if not exists idx_territory_scans_grade on territory_scans(territory_grade);


-- ────────────────────────────────────────────────────────────
-- proposals: generated proposals
-- ────────────────────────────────────────────────────────────
create table if not exists proposals (
  id              uuid primary key default uuid_generate_v4(),
  created_at      timestamp with time zone default now(),

  lead_id         uuid references solar_leads(id),
  ghl_contact_id  text,
  customer_name   text,
  rep_name        text,
  rep_id          text,

  proposal_data   jsonb not null,
  status          text default 'draft' check (status in ('draft','sent','viewed','accepted','rejected')),
  sent_at         timestamp with time zone,
  viewed_at       timestamp with time zone
);


-- ────────────────────────────────────────────────────────────
-- Useful views
-- ────────────────────────────────────────────────────────────

-- Hot leads ready to call
create or replace view hot_leads_dashboard as
  select
    id, formatted_address, city, state, postal_code,
    lead_score, lead_grade, priority,
    system_size_kw, panels_recommended,
    annual_savings_yr1_usd, net_cost_usd, payback_years, roi_25yr_pct,
    monthly_bill_usd, sunshine_hours_per_year,
    status, created_at
  from solar_leads
  where priority in ('HOT', 'WARM')
    and status = 'new'
  order by lead_score desc, created_at desc;


-- Territory performance summary
create or replace view territory_performance as
  select
    postal_code,
    count(*) as total_leads,
    count(*) filter (where priority = 'HOT') as hot_leads,
    count(*) filter (where priority = 'WARM') as warm_leads,
    round(avg(lead_score), 1) as avg_score,
    round(avg(annual_savings_yr1_usd), 0) as avg_annual_savings,
    round(avg(payback_years), 1) as avg_payback
  from solar_leads
  group by postal_code
  order by avg_score desc;


-- ────────────────────────────────────────────────────────────
-- Row Level Security (enable after setup)
-- ────────────────────────────────────────────────────────────
-- alter table solar_leads enable row level security;
-- alter table territory_scans enable row level security;
-- alter table proposals enable row level security;

-- Create a service role policy (for backend API access)
-- create policy "Service role full access" on solar_leads
--   using (true) with check (true);
"""

if __name__ == "__main__":
    print("Supabase Schema SQL:")
    print("=" * 60)
    print(SCHEMA_SQL)
    print("=" * 60)
    print("\nCopy the SQL above and run it in your Supabase SQL editor.")
    print("URL: https://app.supabase.com → Your Project → SQL Editor")
