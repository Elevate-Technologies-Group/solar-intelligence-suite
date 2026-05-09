#!/usr/bin/env python3
"""
solar_incentives.py — Solar Incentives Database & Lookup Tool
Solar Intelligence Suite | Elevate Technologies Group

Comprehensive database of federal, state, and utility solar incentives.
Returns the full incentive stack for any state/ZIP with real dollar amounts.

Usage:
    python scripts/solar_incentives.py AZ --kw 6.4 --cost 19200
    python scripts/solar_incentives.py "1905 E Marquette Dr, Gilbert AZ" --bill 175
    python scripts/solar_incentives.py AZ --json
    python scripts/solar_incentives.py --list-states
"""

import argparse
import json
import os
import sys
from datetime import date

# ─────────────────────────────────────────────────────────────────────────────
# INCENTIVE DATABASE
# Sources: DSIRE (dsireusa.org), IRS, state tax agencies (as of 2025)
# ─────────────────────────────────────────────────────────────────────────────

FEDERAL_INCENTIVES = [
    {
        "id": "federal_itc",
        "name": "Federal Investment Tax Credit (ITC)",
        "authority": "Federal",
        "type": "Tax Credit",
        "calc_type": "pct_gross",
        "value": 0.30,
        "max_usd": None,                 # uncapped
        "expires": "2032-12-31",
        "stacks_with_state": True,
        "description": (
            "30% federal tax credit on total installed solar system cost "
            "(equipment + labor + permits). Applies to systems installed through "
            "2032. Steps down to 26% in 2033, 22% in 2034, 0% for residential "
            "in 2035 unless Congress extends."
        ),
        "talking_point": (
            "The 30% federal ITC saves you ${itc_usd:,.0f} off the top — "
            "that's money directly back on your tax return, not a deduction."
        ),
        "reference": "IRS Form 5695 | IRC Section 25D",
    },
]

# State incentives — keyed by 2-letter state abbreviation
# Each state lists its current active incentives
STATE_INCENTIVES = {

    # ── ARIZONA ──────────────────────────────────────────────────────────────
    "AZ": [
        {
            "id": "az_state_tax_credit",
            "name": "Arizona Residential Solar Energy Tax Credit",
            "authority": "AZ Dept of Revenue",
            "type": "State Tax Credit",
            "calc_type": "pct_gross",
            "value": 0.25,
            "max_usd": 1000,
            "expires": "ongoing",
            "stacks_with_federal": True,
            "description": (
                "25% of total system cost as an Arizona state income tax credit, "
                "capped at $1,000. Stackable with the federal ITC. "
                "Can carry forward unused credit for up to 5 years."
            ),
            "talking_point": (
                "Arizona gives you an extra ${incentive_usd:,.0f} state tax credit "
                "on top of the federal savings — that's both federal AND state "
                "governments paying you to go solar."
            ),
            "reference": "ARS § 43-1083 | AZ Form 310",
        },
        {
            "id": "az_property_tax_exemption",
            "name": "AZ Residential Solar Property Tax Exemption",
            "authority": "AZ Dept of Revenue",
            "type": "Property Tax Exemption",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "stacks_with_federal": True,
            "description": (
                "Solar panels do NOT increase your assessed property value for "
                "property tax purposes in Arizona. A 6.4kW system typically adds "
                "$15,000–$20,000 to home market value — all tax-exempt."
            ),
            "talking_point": (
                "Your home value goes up by roughly ${home_value_increase:,.0f} "
                "with solar — but Arizona law says your property taxes "
                "won't go up a single dollar. You get the equity, not the bill."
            ),
            "reference": "ARS § 42-11054",
        },
        {
            "id": "az_sales_tax_exemption",
            "name": "AZ Solar Equipment Sales Tax Exemption",
            "authority": "AZ Dept of Revenue",
            "type": "Sales Tax Exemption",
            "calc_type": "pct_equipment",
            "value": 0.056,        # AZ base state sales tax
            "max_usd": None,
            "expires": "ongoing",
            "stacks_with_federal": True,
            "description": (
                "No state or local sales tax on solar energy equipment in Arizona "
                "(TPT exemption). On a typical 6–8kW system, saves $800–$1,500 "
                "vs. standard taxable purchases."
            ),
            "talking_point": (
                "Arizona waives all sales tax on solar equipment — saving you "
                "roughly ${incentive_usd:,.0f} right at purchase."
            ),
            "reference": "ARS § 42-5075(B)(7)",
        },
        {
            "id": "aps_rebate",
            "name": "APS (Arizona Public Service) Solar Rebate",
            "authority": "APS / Arizona Corporation Commission",
            "type": "Utility Rebate",
            "calc_type": "per_kw",
            "value": 75,           # $75/kW AC — check current availability
            "max_usd": 600,
            "expires": "limited_funding",
            "stacks_with_federal": True,
            "description": (
                "APS offers rebates of ~$75/kW AC for qualifying residential "
                "rooftop solar. Program availability depends on utility zone. "
                "Subject to annual funding caps — first-come, first-served."
            ),
            "talking_point": (
                "If you're in APS territory, you may qualify for an additional "
                "${incentive_usd:,.0f} utility rebate on top of everything else."
            ),
            "reference": "APS Solar Partner Program",
            "zip_filter": None,    # All APS territory — runtime check not implemented
            "conditional": True,   # Only if in APS territory
        },
        {
            "id": "srp_excess_energy",
            "name": "SRP (Salt River Project) Excess Energy Credit",
            "authority": "Salt River Project",
            "type": "Net Metering / Export Credit",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "stacks_with_federal": True,
            "description": (
                "SRP customers earn credits for excess solar energy exported to "
                "the grid. Credits applied to future bills. SRP uses the "
                "Customer Generation Price Plan — rates vary by season and time."
            ),
            "talking_point": (
                "Your solar system will export extra energy back to the grid — "
                "SRP credits your account, making your net bill even lower "
                "in spring and fall when you produce more than you use."
            ),
            "reference": "SRP Customer Generation Price Plan",
            "conditional": True,
        },
    ],

    # ── CALIFORNIA ───────────────────────────────────────────────────────────
    "CA": [
        {
            "id": "ca_nem3",
            "name": "CA Net Energy Metering (NEM 3.0)",
            "authority": "California PUC / SCE / PG&E / SDG&E",
            "type": "Net Metering",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "NEM 3.0 credits solar exports at avoided-cost rates (~$0.04–0.08/kWh). "
                "Pairs best with battery storage. SCE, PG&E, SDG&E territory. "
                "Encourages self-consumption and evening battery discharge."
            ),
            "talking_point": (
                "California's NEM 3.0 still credits your excess solar — and pairing "
                "with a battery maximizes your savings by using your own power "
                "at peak evening rates."
            ),
            "reference": "CPUC Decision 22-12-056",
        },
        {
            "id": "ca_property_tax_exclusion",
            "name": "CA Active Solar Energy Property Tax Exclusion",
            "authority": "California Board of Equalization",
            "type": "Property Tax Exemption",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "2027-01-01",
            "description": (
                "Solar installations are excluded from property tax reassessment "
                "in California through at least 2027. A $20,000 solar system "
                "avoids ~$200–400/yr in additional property taxes."
            ),
            "talking_point": (
                "California won't raise your property taxes for going solar — "
                "a savings of hundreds of dollars per year on top of your "
                "electricity bill savings."
            ),
            "reference": "Cal. Revenue & Taxation Code § 73",
        },
        {
            "id": "ca_selfgen_incentive",
            "name": "CA SGIP Battery Storage Incentive",
            "authority": "CA Public Utilities Commission",
            "type": "State Rebate",
            "calc_type": "per_kwh_storage",
            "value": 200,          # ~$200/kWh for residential
            "max_usd": 2000,
            "expires": "limited_funding",
            "description": (
                "Self-Generation Incentive Program (SGIP) provides rebates for "
                "home battery storage paired with solar. Equity and equity resilience "
                "tiers offer even higher amounts for qualifying customers."
            ),
            "talking_point": (
                "California's SGIP program pays you up to $2,000 to add a battery "
                "to your solar system — and batteries are now the #1 way to "
                "maximize savings under NEM 3.0."
            ),
            "reference": "CPUC SGIP Program",
            "conditional": True,
        },
    ],

    # ── TEXAS ─────────────────────────────────────────────────────────────────
    "TX": [
        {
            "id": "tx_property_tax_exemption",
            "name": "TX Residential Solar Property Tax Exemption",
            "authority": "Texas Comptroller",
            "type": "Property Tax Exemption",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "100% of the added home value from solar is exempt from Texas "
                "property taxes. A $20,000 solar system adding $18,000 to home "
                "value saves $360–540/yr in property taxes at typical TX rates."
            ),
            "talking_point": (
                "Texas fully exempts your solar-added home equity from property "
                "taxes — you get the increased home value without the tax bill."
            ),
            "reference": "Texas Tax Code § 11.27",
        },
        {
            "id": "tx_sales_tax_exemption",
            "name": "TX Solar Energy Device Sales Tax Exemption",
            "authority": "Texas Comptroller",
            "type": "Sales Tax Exemption",
            "calc_type": "pct_equipment",
            "value": 0.0625,       # TX state sales tax 6.25%
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "Solar energy devices are fully exempt from Texas sales tax "
                "(6.25% state + local). On a $15,000 equipment cost, "
                "this saves approximately $940–1,500."
            ),
            "talking_point": (
                "Texas charges zero sales tax on solar equipment — saving you "
                "roughly ${incentive_usd:,.0f} right at installation."
            ),
            "reference": "Texas Tax Code § 151.317",
        },
    ],

    # ── FLORIDA ───────────────────────────────────────────────────────────────
    "FL": [
        {
            "id": "fl_property_tax_exemption",
            "name": "FL Residential Renewable Energy Property Tax Exemption",
            "authority": "Florida Dept of Revenue",
            "type": "Property Tax Exemption",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "2037-01-01",
            "description": (
                "Solar equipment is fully exempt from Florida property taxes. "
                "Voter-approved constitutional exemption through 2037. "
                "Saves $300–600/yr for a typical residential system."
            ),
            "talking_point": (
                "Florida's constitution protects your solar investment from "
                "property taxes — that's hundreds per year in additional savings "
                "guaranteed through 2037."
            ),
            "reference": "Florida Statute § 193.624",
        },
        {
            "id": "fl_sales_tax_exemption",
            "name": "FL Solar Energy Sales Tax Exemption",
            "authority": "Florida Dept of Revenue",
            "type": "Sales Tax Exemption",
            "calc_type": "pct_equipment",
            "value": 0.06,         # FL state sales tax 6%
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "Solar energy systems and components are exempt from Florida's "
                "6% state sales tax. Local surtax may apply in some counties."
            ),
            "talking_point": (
                "Florida waives its 6% sales tax on solar — that's another "
                "${incentive_usd:,.0f} in your pocket at installation."
            ),
            "reference": "Florida Statute § 212.08(7)(hh)",
        },
        {
            "id": "fl_net_metering",
            "name": "FL Net Metering",
            "authority": "Florida PSC",
            "type": "Net Metering",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "Florida investor-owned utilities must offer net metering. "
                "Excess generation credited at retail rate. FPL, Duke, TECO "
                "all participate. Up to 2 MW for residential."
            ),
            "talking_point": (
                "Florida net metering means every extra kilowatt you generate "
                "rolls back your meter — your utility is basically your battery."
            ),
            "reference": "Florida PSC Rule 25-6.065",
        },
    ],

    # ── NEVADA ────────────────────────────────────────────────────────────────
    "NV": [
        {
            "id": "nv_property_tax_exemption",
            "name": "NV Residential Solar Property Tax Abatement",
            "authority": "Nevada Dept of Taxation",
            "type": "Property Tax Exemption",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "Nevada exempts the added value of solar from property taxes for "
                "up to 10 years. Applies to systems ≤25 kW residential."
            ),
            "talking_point": (
                "Nevada won't raise your property taxes for solar — for 10 years "
                "the added home value is completely protected."
            ),
            "reference": "NRS § 361.0785",
        },
        {
            "id": "nv_sales_tax_exemption",
            "name": "NV Solar Energy Equipment Sales Tax Exemption",
            "authority": "Nevada Dept of Taxation",
            "type": "Sales Tax Exemption",
            "calc_type": "pct_equipment",
            "value": 0.0685,
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "Nevada exempts solar energy systems from sales and use tax "
                "(currently 6.85% base rate). Significant savings on equipment."
            ),
            "talking_point": (
                "Nevada charges zero sales tax on solar equipment — that's "
                "${incentive_usd:,.0f} in immediate savings."
            ),
            "reference": "NRS § 374.357",
        },
    ],

    # ── COLORADO ──────────────────────────────────────────────────────────────
    "CO": [
        {
            "id": "co_sales_tax_exemption",
            "name": "CO Residential Solar Equipment Sales Tax Exemption",
            "authority": "Colorado Dept of Revenue",
            "type": "Sales Tax Exemption",
            "calc_type": "pct_equipment",
            "value": 0.029,        # CO state rate 2.9%
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "Colorado exempts residential solar installations from state "
                "sales tax (2.9%). Some counties also exempt local taxes."
            ),
            "talking_point": (
                "Colorado's solar sales tax exemption saves you "
                "${incentive_usd:,.0f} in state taxes at purchase."
            ),
            "reference": "CRS § 39-26-724",
        },
        {
            "id": "xcel_rebate",
            "name": "Xcel Energy Solar*Rewards Rebate",
            "authority": "Xcel Energy / CPUC",
            "type": "Utility Rebate",
            "calc_type": "per_kw",
            "value": 50,
            "max_usd": 500,
            "expires": "limited_funding",
            "description": (
                "Xcel Energy's Solar*Rewards program offers performance-based "
                "incentives for solar systems in Colorado. Amounts vary by "
                "program tier and funding availability."
            ),
            "talking_point": (
                "If you're in Xcel territory, you may qualify for an additional "
                "${incentive_usd:,.0f} rebate from your utility."
            ),
            "reference": "Xcel Energy Solar*Rewards Program",
            "conditional": True,
        },
    ],

    # ── NEW MEXICO ────────────────────────────────────────────────────────────
    "NM": [
        {
            "id": "nm_tax_credit",
            "name": "NM Solar Market Development Tax Credit",
            "authority": "NM Taxation & Revenue Dept",
            "type": "State Tax Credit",
            "calc_type": "pct_gross",
            "value": 0.10,
            "max_usd": 9000,
            "expires": "2032-12-31",
            "description": (
                "New Mexico offers a 10% state income tax credit on residential "
                "solar installations, capped at $9,000. Stackable with federal ITC."
            ),
            "talking_point": (
                "New Mexico adds a 10% state tax credit on top of the 30% federal — "
                "that's 40% combined tax credits, saving you ${incentive_usd:,.0f} "
                "more in state taxes."
            ),
            "reference": "NMSA 1978 § 7-2-18.29",
        },
        {
            "id": "nm_property_tax_exemption",
            "name": "NM Solar Property Tax Exemption",
            "authority": "NM Taxation & Revenue",
            "type": "Property Tax Exemption",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "Solar energy systems are exempt from NM property tax assessment."
            ),
            "talking_point": (
                "New Mexico guarantees your solar won't raise your property taxes."
            ),
            "reference": "NMSA 1978 § 7-36-27",
        },
    ],

    # ── UTAH ──────────────────────────────────────────────────────────────────
    "UT": [
        {
            "id": "ut_tax_credit",
            "name": "UT Renewable Energy Systems Tax Credit",
            "authority": "Utah State Tax Commission",
            "type": "State Tax Credit",
            "calc_type": "pct_gross",
            "value": 0.25,
            "max_usd": 1600,
            "expires": "ongoing",
            "description": (
                "Utah offers a 25% residential solar tax credit capped at $1,600 "
                "(systems >2 kW). Can be carried forward up to 4 years."
            ),
            "talking_point": (
                "Utah adds ${incentive_usd:,.0f} in state tax credits on top of "
                "the 30% federal ITC — Utah actively rewards going solar."
            ),
            "reference": "Utah Code Ann. § 59-10-1014",
        },
    ],

    # ── HAWAII ────────────────────────────────────────────────────────────────
    "HI": [
        {
            "id": "hi_tax_credit",
            "name": "HI Renewable Energy Technologies Income Tax Credit",
            "authority": "Hawaii Dept of Taxation",
            "type": "State Tax Credit",
            "calc_type": "pct_gross",
            "value": 0.35,
            "max_usd": 5000,
            "expires": "ongoing",
            "description": (
                "Hawaii's 35% solar tax credit (capped at $5,000) is one of "
                "the most generous in the nation. Stacks with 30% federal ITC — "
                "combined 65% of system cost covered by tax credits."
            ),
            "talking_point": (
                "Hawaii's 35% state tax credit adds ${incentive_usd:,.0f} — "
                "combined with federal ITC that's over 60% of your system cost "
                "covered by tax credits."
            ),
            "reference": "HRS § 235-12.5",
        },
    ],

    # ── NEW YORK ──────────────────────────────────────────────────────────────
    "NY": [
        {
            "id": "ny_tax_credit",
            "name": "NY Residential Solar Tax Credit",
            "authority": "NY Dept of Taxation & Finance",
            "type": "State Tax Credit",
            "calc_type": "pct_gross",
            "value": 0.25,
            "max_usd": 5000,
            "expires": "ongoing",
            "description": (
                "New York offers a 25% residential solar tax credit up to $5,000 "
                "on qualified solar electric and solar thermal systems."
            ),
            "talking_point": (
                "New York State adds ${incentive_usd:,.0f} in state tax credits "
                "— on top of the 30% federal ITC."
            ),
            "reference": "NY Tax Law § 606(g-1)",
        },
        {
            "id": "nyserda_rebate",
            "name": "NY-Sun Megawatt Block Incentive (NYSERDA)",
            "authority": "NYSERDA",
            "type": "State Rebate",
            "calc_type": "per_kw",
            "value": 200,
            "max_usd": 2000,
            "expires": "limited_funding",
            "description": (
                "NYSERDA's NY-Sun program offers per-kW rebates on residential "
                "solar. Block incentive levels decrease as more solar is deployed. "
                "Check current block pricing at nyserda.ny.gov."
            ),
            "talking_point": (
                "NY-Sun's NYSERDA rebate could add another ${incentive_usd:,.0f} "
                "to your total savings package."
            ),
            "reference": "NYSERDA NY-Sun",
            "conditional": True,
        },
        {
            "id": "ny_property_tax_exemption",
            "name": "NY Solar Energy System Property Tax Exemption",
            "authority": "NY State / Local",
            "type": "Property Tax Exemption",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "New York exempts solar installations from real property taxation "
                "for 15 years from initial installation."
            ),
            "talking_point": (
                "New York law protects your solar home equity from property "
                "taxes for 15 full years."
            ),
            "reference": "NY Real Property Tax Law § 487",
        },
    ],

    # ── MASSACHUSETTS ─────────────────────────────────────────────────────────
    "MA": [
        {
            "id": "ma_tax_credit",
            "name": "MA Residential Renewable Energy Tax Credit",
            "authority": "MA Dept of Revenue",
            "type": "State Tax Credit",
            "calc_type": "pct_gross",
            "value": 0.15,
            "max_usd": 1000,
            "expires": "ongoing",
            "description": (
                "Massachusetts offers a 15% solar tax credit capped at $1,000 "
                "for residential solar installations."
            ),
            "talking_point": (
                "Massachusetts adds ${incentive_usd:,.0f} in state solar tax "
                "credits to your federal savings."
            ),
            "reference": "MGL Chapter 62 § 6(d)",
        },
        {
            "id": "ma_srec",
            "name": "MA SMART Program (Solar Incentive)",
            "authority": "MA DOER / Eversource / National Grid / Unitil",
            "type": "Performance Incentive",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "limited_funding",
            "description": (
                "SMART (Solar Massachusetts Renewable Target) pays a fixed "
                "monthly compensation per kWh for 10 years. Rates vary by "
                "capacity block and utility territory."
            ),
            "talking_point": (
                "Massachusetts SMART program pays you for every kWh your system "
                "produces for 10 years — a guaranteed revenue stream on top of "
                "your bill savings."
            ),
            "reference": "MA DOER SMART Program",
            "conditional": True,
        },
    ],

    # ── MARYLAND ──────────────────────────────────────────────────────────────
    "MD": [
        {
            "id": "md_grant",
            "name": "MD Clean Energy Grant Program",
            "authority": "Maryland Energy Administration",
            "type": "State Grant",
            "calc_type": "flat",
            "value": 1000,
            "max_usd": 1000,
            "expires": "limited_funding",
            "description": (
                "Maryland Energy Administration offers $1,000 grants for "
                "residential solar installations. Subject to funding availability."
            ),
            "talking_point": (
                "Maryland's clean energy grant provides a ${incentive_usd:,.0f} "
                "rebate directly off your installation — no tax filing needed."
            ),
            "reference": "MEA Residential Clean Energy Grant Program",
            "conditional": True,
        },
        {
            "id": "md_property_tax_exemption",
            "name": "MD Solar Energy Property Tax Credit",
            "authority": "MD State Dept of Assessments",
            "type": "Property Tax Exemption",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "Maryland law exempts solar energy equipment from property tax "
                "assessment — your home value increase from solar is tax-free."
            ),
            "talking_point": (
                "Maryland won't tax the added home equity from your solar system."
            ),
            "reference": "MD Tax-Property Article § 9-203",
        },
    ],

    # ── SOUTH CAROLINA ────────────────────────────────────────────────────────
    "SC": [
        {
            "id": "sc_tax_credit",
            "name": "SC Residential Renewable Energy Tax Credit",
            "authority": "SC Dept of Revenue",
            "type": "State Tax Credit",
            "calc_type": "pct_gross",
            "value": 0.25,
            "max_usd": 3500,
            "expires": "ongoing",
            "description": (
                "South Carolina offers a 25% residential solar tax credit, "
                "capped at $3,500. Unused credit can be carried forward up to 10 years."
            ),
            "talking_point": (
                "South Carolina's 25% state tax credit adds ${incentive_usd:,.0f} "
                "on top of the federal ITC — SC is very solar-friendly."
            ),
            "reference": "SC Code § 12-6-3587",
        },
    ],

    # ── NORTH CAROLINA ────────────────────────────────────────────────────────
    "NC": [
        {
            "id": "nc_property_tax_exemption",
            "name": "NC Solar Energy Property Tax Exclusion",
            "authority": "NC Dept of Revenue",
            "type": "Property Tax Exemption",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "80% of the added value from a solar energy system is excluded "
                "from NC property taxes. (Only 20% of solar added value is taxed.)"
            ),
            "talking_point": (
                "North Carolina only taxes 20% of the home equity boost from "
                "solar — saving you hundreds per year in property taxes."
            ),
            "reference": "NC General Statutes § 105-277.3A",
        },
    ],

    # ── VIRGINIA ──────────────────────────────────────────────────────────────
    "VA": [
        {
            "id": "va_property_tax_exemption",
            "name": "VA Residential Solar Property Tax Exemption",
            "authority": "Virginia Dept of Taxation",
            "type": "Property Tax Exemption",
            "calc_type": "flat_note",
            "value": 0,
            "max_usd": None,
            "expires": "ongoing",
            "description": (
                "Virginia localities may fully exempt solar systems from property "
                "taxes (most do). Both the equipment and added home value "
                "are exempt."
            ),
            "talking_point": (
                "Virginia protects your solar investment from property taxes — "
                "the equity boost is yours to keep."
            ),
            "reference": "Code of Virginia § 58.1-3661",
        },
    ],
}

# States with no significant additional incentives beyond federal ITC
# (still list so we can give accurate info)
MINIMAL_INCENTIVE_STATES = {
    "GA", "AL", "MS", "TN", "KY", "IN", "OH", "WI", "MN", "IA", "MO",
    "AR", "LA", "OK", "KS", "NE", "SD", "ND", "WY", "MT", "ID",
}

# ─────────────────────────────────────────────────────────────────────────────
# CORE FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_incentives(
    state: str,
    postal_code: str = None,
    gross_cost_usd: float = 20000.0,
    system_size_kw: float = 6.0,
    panel_count: int = 20,
) -> dict:
    """
    Returns the full incentive stack for a state, with real dollar amounts.

    Parameters
    ----------
    state          : 2-letter state abbreviation (e.g., "AZ")
    postal_code    : ZIP code for future utility-zone lookup
    gross_cost_usd : Total installed system cost (before any credits)
    system_size_kw : System size in kW AC
    panel_count    : Number of panels

    Returns
    -------
    {
        state, postal_code, gross_cost_usd, system_size_kw,
        federal_incentives: [...],
        state_incentives: [...],
        total_federal_usd: float,
        total_state_usd: float,
        total_savings_usd: float,
        net_cost_after_incentives: float,
        effective_discount_pct: float,
        summary_line: str,          # "Save $7,960 total — net cost $11,240"
        talking_points: [...],
        has_state_incentives: bool,
        state_known: bool,
    }
    """
    state = state.upper().strip()
    equipment_cost = gross_cost_usd * 0.60    # ~60% of gross is equipment cost

    def calc_incentive_usd(inc: dict) -> float:
        ct = inc.get("calc_type", "")
        if ct == "pct_gross":
            amt = gross_cost_usd * inc["value"]
            return min(amt, inc["max_usd"]) if inc.get("max_usd") else amt
        elif ct == "pct_equipment":
            amt = equipment_cost * inc["value"]
            return min(amt, inc["max_usd"]) if inc.get("max_usd") else amt
        elif ct == "per_kw":
            amt = system_size_kw * inc["value"]
            return min(amt, inc["max_usd"]) if inc.get("max_usd") else amt
        elif ct == "flat":
            return float(inc["value"])
        elif ct == "per_kwh_storage":
            # Estimate 10 kWh battery default
            amt = 10 * inc["value"]
            return min(amt, inc["max_usd"]) if inc.get("max_usd") else amt
        else:
            return 0.0  # flat_note = informational, no direct dollar amount

    def format_talking_point(template: str, incentive_usd: float, itc_usd: float) -> str:
        home_value_increase = system_size_kw * 3000   # ~$3k/kW added value estimate
        try:
            return template.format(
                incentive_usd=incentive_usd,
                itc_usd=itc_usd,
                home_value_increase=home_value_increase,
            )
        except Exception:
            return template

    # Federal incentives
    itc_usd = gross_cost_usd * 0.30
    federal_results = []
    for inc in FEDERAL_INCENTIVES:
        usd = calc_incentive_usd(inc)
        result = {**inc}
        result["incentive_usd"] = round(usd, 2)
        tp = inc.get("talking_point", "")
        result["talking_point_formatted"] = format_talking_point(tp, usd, itc_usd)
        federal_results.append(result)

    total_federal = sum(r["incentive_usd"] for r in federal_results)

    # State incentives
    state_incentives_raw = STATE_INCENTIVES.get(state, [])
    state_results = []
    for inc in state_incentives_raw:
        usd = calc_incentive_usd(inc)
        result = {**inc}
        result["incentive_usd"] = round(usd, 2)
        tp = inc.get("talking_point", "")
        result["talking_point_formatted"] = format_talking_point(tp, usd, itc_usd)
        state_results.append(result)

    # Total state dollar value (exclude pure notes)
    total_state = sum(
        r["incentive_usd"] for r in state_results
        if r.get("calc_type") != "flat_note"
    )

    total_savings = total_federal + total_state
    net_cost = gross_cost_usd - total_savings
    discount_pct = (total_savings / gross_cost_usd * 100) if gross_cost_usd > 0 else 0

    summary_line = (
        f"Save ${total_savings:,.0f} total in incentives — "
        f"net cost ${net_cost:,.0f} "
        f"({discount_pct:.0f}% off gross)"
    )

    # Collect all talking points
    all_talking_points = []
    for r in federal_results:
        tp = r.get("talking_point_formatted", "")
        if tp:
            all_talking_points.append(tp)
    for r in state_results:
        tp = r.get("talking_point_formatted", "")
        if tp:
            all_talking_points.append(tp)

    state_known = state in STATE_INCENTIVES or state in MINIMAL_INCENTIVE_STATES

    return {
        "state": state,
        "postal_code": postal_code,
        "gross_cost_usd": round(gross_cost_usd, 2),
        "system_size_kw": system_size_kw,
        "panel_count": panel_count,

        "federal_incentives": federal_results,
        "state_incentives": state_results,

        "total_federal_usd": round(total_federal, 2),
        "total_state_usd": round(total_state, 2),
        "total_savings_usd": round(total_savings, 2),
        "net_cost_after_incentives": round(net_cost, 2),
        "effective_discount_pct": round(discount_pct, 1),

        "summary_line": summary_line,
        "talking_points": all_talking_points,

        "has_state_incentives": bool(state_results),
        "state_known": state_known,
        "state_in_minimal_category": state in MINIMAL_INCENTIVE_STATES,
        "data_as_of": "2025-01-01",
        "disclaimer": (
            "Incentive amounts are estimates based on typical system costs. "
            "Consult a tax professional for exact figures. Program availability "
            "and funding subject to change."
        ),
    }


def list_states_with_incentives() -> list:
    """Returns list of states with known state-level incentives."""
    return sorted(STATE_INCENTIVES.keys())


# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL REPORT
# ─────────────────────────────────────────────────────────────────────────────

def _c(code: str, text: str, no_color: bool = False) -> str:
    if no_color:
        return text
    return f"\033[{code}m{text}\033[0m"

def print_incentives_report(result: dict, no_color: bool = False, address: str = None):
    W = 70
    state = result["state"]
    gross = result["gross_cost_usd"]
    net = result["net_cost_after_incentives"]
    total_savings = result["total_savings_usd"]
    federal_usd = result["total_federal_usd"]
    state_usd = result["total_state_usd"]
    discount = result["effective_discount_pct"]

    # Header
    print(_c("1;34", "═" * W, no_color))
    title = f"☀  SOLAR INCENTIVES — {state}"
    if address:
        title += f"  ({address[:35]})"
    print(_c("1;37", f"  {title}", no_color))
    print(_c("1;34", "═" * W, no_color))
    print()

    # Cost summary box
    print(_c("1;33", "  TOTAL INCENTIVE STACK:", no_color))
    print(f"  {'Gross System Cost:':<30} ${gross:>10,.0f}")
    print(_c("32", f"  {'Federal ITC (30%):':<30} -${federal_usd:>9,.0f}", no_color))
    if state_usd > 0:
        print(_c("32", f"  {'State Incentives:':<30} -${state_usd:>9,.0f}", no_color))
    print(_c("1;33", "  " + "─" * 44, no_color))
    print(_c("1;32", f"  {'NET COST AFTER INCENTIVES:':<30} ${net:>10,.0f}", no_color))
    print()
    bar_filled = int(discount / 100 * 40)
    bar = "█" * bar_filled + "░" * (40 - bar_filled)
    print(_c("1;35", f"  {discount:.0f}% discount: [{bar}]", no_color))
    print()

    # Federal incentives
    print(_c("1;36", "  FEDERAL INCENTIVES:", no_color))
    for inc in result["federal_incentives"]:
        usd_str = f"${inc['incentive_usd']:,.0f}"
        print(f"  ✅ {inc['name']}")
        print(f"     {_c('33', usd_str, no_color)} | {inc['type']} | {inc.get('expires','?')}")
        print(f"     {inc['description'][:80]}")
        print()

    # State incentives
    if result["state_incentives"]:
        print(_c("1;36", f"  {state} STATE INCENTIVES:", no_color))
        for inc in result["state_incentives"]:
            usd_str = f"${inc['incentive_usd']:,.0f}" if inc["incentive_usd"] > 0 else "Note"
            cond = " ⚠ (conditional)" if inc.get("conditional") else ""
            print(f"  ✅ {inc['name']}{cond}")
            print(f"     {_c('33', usd_str, no_color)} | {inc['type']}")
            print(f"     {inc['description'][:80]}")
            print()
    else:
        note = "minimal" if result.get("state_in_minimal_category") else "not yet tracked"
        print(_c("33", f"  ⚠  No additional state incentives found for {state} ({note}).", no_color))
        print(_c("33", "     Federal ITC applies in all 50 states.", no_color))
        print()

    # Talking points
    print(_c("1;35", "  REP TALKING POINTS:", no_color))
    for i, tp in enumerate(result["talking_points"][:5], 1):
        # Word wrap at 66 chars
        words = tp.split()
        lines = []
        current = ""
        for w in words:
            if len(current) + len(w) + 1 > 64:
                lines.append(current)
                current = w
            else:
                current = (current + " " + w).strip()
        if current:
            lines.append(current)
        print(f"  {i}. {lines[0]}")
        for line in lines[1:]:
            print(f"     {line}")
        print()

    # Disclaimer
    print(_c("90", f"  Data as of {result['data_of'] if 'data_of' in result else '2025'}. Consult a tax professional for exact figures.", no_color))
    print(_c("1;34", "═" * W, no_color))


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Solar Incentives Lookup — federal + state + utility incentives",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/solar_incentives.py AZ --kw 6.4 --cost 19200
  python scripts/solar_incentives.py CA --cost 25000 --kw 8.0
  python scripts/solar_incentives.py --list-states
  python scripts/solar_incentives.py AZ --json
        """,
    )
    parser.add_argument("state_or_address", nargs="?", default="AZ",
                        help="2-letter state code or address string")
    parser.add_argument("--cost", type=float, default=20000,
                        help="Gross system cost in USD (default: $20,000)")
    parser.add_argument("--kw", type=float, default=6.0,
                        help="System size in kW (default: 6.0)")
    parser.add_argument("--panels", type=int, default=20,
                        help="Panel count (default: 20)")
    parser.add_argument("--zip", default=None, help="ZIP code for utility lookup")
    parser.add_argument("--bill", type=float, default=None,
                        help="Monthly bill — auto-estimates cost/kW if no --cost")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--list-states", action="store_true",
                        help="List all states with tracked incentives")
    args = parser.parse_args()

    if args.list_states:
        states = list_states_with_incentives()
        print("States with tracked solar incentives:")
        for s in states:
            count = len(STATE_INCENTIVES[s])
            print(f"  {s} — {count} incentive program(s)")
        print(f"\nTotal: {len(states)} states tracked")
        print("Federal ITC (30%) applies in all 50 states.")
        return

    # Determine state
    target = args.state_or_address.strip()
    state = target[:2].upper() if len(target) <= 3 else None
    address = None

    if not state or len(target) > 2:
        # Try to extract state from address
        parts = target.replace(",", " ").split()
        # Look for 2-letter uppercase token
        for p in reversed(parts):
            if len(p) == 2 and p.isalpha():
                state = p.upper()
                address = target
                break
        if not state:
            state = "AZ"  # Default

    gross_cost = args.cost
    # If bill given and no explicit cost, estimate
    if args.bill and args.cost == 20000:
        kw_estimated = args.bill / 175 * 6.0   # rough: $175 bill ~= 6kW
        gross_cost = kw_estimated * 3000         # ~$3/W installed
        args.kw = round(kw_estimated, 1)
        args.panels = int(args.kw * 3)

    result = get_incentives(
        state=state,
        postal_code=args.zip,
        gross_cost_usd=gross_cost,
        system_size_kw=args.kw,
        panel_count=args.panels,
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print_incentives_report(result, no_color=args.no_color, address=address)


if __name__ == "__main__":
    main()
