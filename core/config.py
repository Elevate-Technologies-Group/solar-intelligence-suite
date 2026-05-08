"""
Central config for Solar Intelligence Suite
All keys loaded from env — never hardcoded
"""
import os

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SOLAR_BASE = "https://solar.googleapis.com/v1"
MAPS_BASE = "https://maps.googleapis.com/maps/api"
PLACES_BASE = "https://places.googleapis.com/v1"

CACHE_DIR = os.path.join(os.path.dirname(__file__), "../cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Cost tracking (rough estimates per call)
COST_SOLAR_API = 0.003       # $3/1000 calls
COST_GEOCODING = 0.005       # $5/1000 calls
COST_PLACES    = 0.032       # $32/1000 calls (nearby search)

# Solar system defaults
DEFAULT_PANEL_COST_USD = 3.00         # per watt installed
DEFAULT_UTILITY_RATE_KWH = 0.14       # avg US residential
DEFAULT_FEDERAL_ITC = 0.30            # 30% federal tax credit
DEFAULT_PANEL_CAPACITY_W = 400        # 400W panels
PANELS_PER_KW = 1000 / DEFAULT_PANEL_CAPACITY_W  # 2.5 panels per kW
