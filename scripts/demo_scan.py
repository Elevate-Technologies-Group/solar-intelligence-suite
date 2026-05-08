#!/usr/bin/env python3
"""Demo territory scan — run from /root/solar-tools"""
import sys, os
sys.path.insert(0, '/root/solar-tools')
os.environ['GOOGLE_MAPS_API_KEY'] = 'AIzaSyAv-Mct8m2zynAFIcaCAwjNOthrDrezGO4'

from tools.territory import scan_territory, multi_zip_comparison
import json

print("=" * 60)
print("TERRITORY SCAN DEMO — Gilbert/Chandler AZ (85234)")
print("=" * 60)

result = scan_territory('85234', sample_size=5, avg_monthly_bill=185)
print(f"ZIP:        {result.get('zip_code')}")
print(f"Grade:      {result.get('territory_grade')}")
print(f"Avg Score:  {result.get('avg_lead_score')}")
print(f"Hot Leads:  {result.get('hot_leads')} / {result.get('leads_enriched')}")
print(f"Avg Yr1:    ${result.get('avg_annual_savings_usd'):,.0f}")
print()
print("TOP PROSPECTS:")
for p in result.get('prospects', []):
    addr = p.get('address', '')[:50]
    grade = p.get('lead_grade', '?')
    score = p.get('lead_score', 0)
    savings = p.get('annual_savings_yr1_usd', 0)
    payback = p.get('payback_years', 0)
    priority = p.get('priority', '')
    print(f"  [{grade}] {priority:<4} Score:{score:>3}/100  Save:${savings:>6,.0f}/yr  Payback:{payback}yr")
    print(f"       {addr}")
    print()

# Save full result
with open('/root/solar-tools/cache/demo_85234.json', 'w') as f:
    json.dump(result, f, indent=2)
print("Full results saved to cache/demo_85234.json")
