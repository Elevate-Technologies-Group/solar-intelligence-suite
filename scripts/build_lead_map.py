#!/usr/bin/env python3
"""
Lead Map Generator
Generates a standalone HTML map page showing all cached leads as color-coded pins.
Also callable via /api/leads/map endpoint.

Usage:
    python scripts/build_lead_map.py [--open] [--print-path] [--output PATH]
"""

import sys, os, json, argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CACHE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "cache"
MAPS_DIR  = CACHE_DIR / "maps"

# ─── Lead Data Collection ─────────────────────────────────────────────────────

def collect_all_leads() -> list:
    """Read all territory + canvass JSON files and return deduplicated leads with lat/lng."""
    leads = {}  # keyed by address

    for f in sorted(CACHE_DIR.glob("territory_*.json")):
        try:
            data = json.loads(f.read_text())
            for p in data.get("prospects", []):
                addr = p.get("address") or p.get("formatted_address", "")
                if addr and p.get("lat") and p.get("lng"):
                    leads[addr] = p
        except Exception:
            pass

    for f in sorted(CACHE_DIR.glob("canvass_*.json")):
        try:
            data = json.loads(f.read_text())
            for s in data.get("canvass_stops", []):
                addr = s.get("address") or s.get("formatted_address", "")
                if addr and s.get("lat") and s.get("lng"):
                    leads[addr] = s
        except Exception:
            pass

    return list(leads.values())


def leads_to_geojson(leads: list) -> dict:
    """Convert leads list to GeoJSON FeatureCollection."""
    features = []
    for lead in leads:
        lat = lead.get("lat")
        lng = lead.get("lng")
        if not lat or not lng:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "address":                  lead.get("address", lead.get("formatted_address", "")),
                "lead_score":               lead.get("lead_score", 0),
                "priority":                 lead.get("priority", "UNKNOWN"),
                "lead_grade":               lead.get("lead_grade", "?"),
                "annual_savings_yr1_usd":   lead.get("annual_savings_yr1_usd", 0),
                "payback_years":            lead.get("payback_years", 0),
                "panels_recommended":       lead.get("panels_recommended", 0),
                "system_size_kw":           lead.get("system_size_kw", 0),
                "sunshine_hours_per_year":  lead.get("sunshine_hours_per_year", 0),
                "talking_points":           lead.get("talking_points", [])[:3],
            }
        })
    return {"type": "FeatureCollection", "features": features}


# ─── HTML Generator ───────────────────────────────────────────────────────────

def generate_map_html(geojson: dict, google_maps_key: str = "", title: str = "Solar Lead Map") -> str:
    """Generate a standalone HTML map page from GeoJSON data."""

    features = geojson.get("features", [])
    total    = len(features)
    hot      = sum(1 for f in features if f["properties"].get("priority") == "HOT")
    warm     = sum(1 for f in features if f["properties"].get("priority") == "WARM")
    pipeline = sum(f["properties"].get("annual_savings_yr1_usd", 0) for f in features
                   if f["properties"].get("priority") in ("HOT", "WARM"))

    avg_lat = 33.4484
    avg_lng = -112.0740
    if features:
        avg_lat = sum(f["geometry"]["coordinates"][1] for f in features) / len(features)
        avg_lng = sum(f["geometry"]["coordinates"][0] for f in features) / len(features)

    geojson_json = json.dumps(geojson, separators=(',', ':'))
    gen_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # ── JavaScript block (NOT an f-string — Python vars substituted after) ──────
    # Use __PYTHON_VAR__ placeholders, then .replace() them in.
    if google_maps_key:
        maps_head = '<script src="https://maps.googleapis.com/maps/api/js?key=__GMAPS_KEY__&callback=initMap" async defer></script>'
        maps_js = r"""
const CENTER = {lat: __LAT__, lng: __LNG__};

function initMap() {
    const map = new google.maps.Map(document.getElementById('map'), {
        center: CENTER, zoom: 13, mapTypeId: 'satellite', tilt: 0,
        styles: [{featureType:'poi',elementType:'labels',stylers:[{visibility:'off'}]}]
    });
    const infoWin = new google.maps.InfoWindow();
    const markers = [];

    const PC = {
        HOT:     {bg:'#ef4444', border:'#b91c1c', text:'#fff'},
        WARM:    {bg:'#f97316', border:'#c2410c', text:'#fff'},
        COOL:    {bg:'#3b82f6', border:'#1d4ed8', text:'#fff'},
        LOW:     {bg:'#6b7280', border:'#374151', text:'#fff'},
        UNKNOWN: {bg:'#9ca3af', border:'#6b7280', text:'#fff'},
    };

    function scoreBar(sc) {
        const p = Math.min(100,sc);
        const c = sc>=80?'#22c55e':sc>=60?'#eab308':sc>=40?'#f97316':'#ef4444';
        return '<div style="background:#1f2937;border-radius:4px;height:8px;width:100%;margin:4px 0">'
             + '<div style="background:'+c+';height:8px;border-radius:4px;width:'+p+'%"></div></div>';
    }

    function makeMarker(feat) {
        const pr = feat.properties;
        const lng = feat.geometry.coordinates[0];
        const lat = feat.geometry.coordinates[1];
        const prio = pr.priority || 'UNKNOWN';
        const col  = PC[prio] || PC.UNKNOWN;
        const sc   = pr.lead_score || 0;

        const svgStr = '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="48" viewBox="0 0 36 48">'
            + '<ellipse cx="18" cy="44" rx="6" ry="3" fill="rgba(0,0,0,0.3)"/>'
            + '<path d="M18 0 C8 0 0 8 0 18 C0 30 18 48 18 48 C18 48 36 30 36 18 C36 8 28 0 18 0Z"'
            + ' fill="'+col.bg+'" stroke="'+col.border+'" stroke-width="2"/>'
            + '<text x="18" y="22" text-anchor="middle" font-size="11" font-weight="bold"'
            + ' font-family="Arial,sans-serif" fill="'+col.text+'">'+sc+'</text></svg>';

        const marker = new google.maps.Marker({
            position: {lat, lng}, map,
            icon: {
                url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svgStr),
                scaledSize: new google.maps.Size(36,48),
                anchor:     new google.maps.Point(18,48),
            },
            title: pr.address, priority: prio,
        });

        const sav  = pr.annual_savings_yr1_usd ? '$'+pr.annual_savings_yr1_usd.toLocaleString()+'/yr' : 'N/A';
        const pay  = pr.payback_years ? pr.payback_years.toFixed(1)+' yrs' : 'N/A';
        const sys  = pr.panels_recommended ? pr.panels_recommended+' panels \u00b7 '+(pr.system_size_kw||0).toFixed(1)+'kW' : 'N/A';
        const sun  = pr.sunshine_hours_per_year ? Math.round(pr.sunshine_hours_per_year)+' hrs/yr' : 'N/A';
        const grd  = pr.lead_grade || '?';
        const pts  = (pr.talking_points||[]).slice(0,2).map(t => '<li style="margin:3px 0;font-size:12px;color:#d1d5db">'+t+'</li>').join('');
        const addr = (pr.address||'').replace(/'/g,'');

        const html = '<div style="background:#111827;border-radius:10px;padding:14px;min-width:280px;max-width:320px;font-family:Arial,sans-serif;color:#f9fafb">'
            + '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
            + '<span style="background:'+col.bg+';color:'+col.text+';padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700">'+prio+'</span>'
            + '<span style="background:#1f2937;color:#fbbf24;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700">'+grd+'</span>'
            + '<span style="color:#9ca3af;font-size:11px;margin-left:auto">Score: <b style="color:#f9fafb">'+sc+'</b>/100</span>'
            + '</div>'
            + scoreBar(sc)
            + '<div style="font-size:13px;font-weight:600;color:#f9fafb;margin-bottom:8px;line-height:1.3">'+pr.address+'</div>'
            + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px">'
            + '<div style="background:#1f2937;padding:8px;border-radius:6px;text-align:center"><div style="color:#22c55e;font-size:15px;font-weight:700">'+sav+'</div><div style="color:#6b7280;font-size:10px">Yr1 Savings</div></div>'
            + '<div style="background:#1f2937;padding:8px;border-radius:6px;text-align:center"><div style="color:#60a5fa;font-size:15px;font-weight:700">'+pay+'</div><div style="color:#6b7280;font-size:10px">Payback</div></div>'
            + '<div style="background:#1f2937;padding:8px;border-radius:6px;text-align:center"><div style="color:#a78bfa;font-size:14px;font-weight:700">'+sys+'</div><div style="color:#6b7280;font-size:10px">System</div></div>'
            + '<div style="background:#1f2937;padding:8px;border-radius:6px;text-align:center"><div style="color:#fbbf24;font-size:15px;font-weight:700">'+sun+'</div><div style="color:#6b7280;font-size:10px">Sunshine</div></div>'
            + '</div>'
            + (pts ? '<ul style="margin:0 0 8px;padding-left:16px">'+pts+'</ul>' : '')
            + '<div style="display:flex;gap:6px;margin-top:4px">'
            + '<button onclick="window.openEnrich(\''+addr+'\',\''+prio+'\')" style="flex:1;padding:7px;background:#2563eb;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-weight:600">\u26a1 Analyze</button>'
            + '<button onclick="window.openProposal(\''+addr+'\',\''+prio+'\')" style="flex:1;padding:7px;background:#7c3aed;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-weight:600">\ud83d\udcc4 Proposal</button>'
            + '</div></div>';

        marker.addListener('click', () => { infoWin.setContent(html); infoWin.open(map, marker); });
        return marker;
    }

    const GEOJSON = __GEOJSON__;
    GEOJSON.features.forEach(f => markers.push(makeMarker(f)));

    window.filterMap = function(prio) {
        markers.forEach(m => m.setVisible(prio==='ALL' || m.priority===prio));
        document.querySelectorAll('.filter-btn').forEach(b => {
            const active = b.dataset.prio===prio || (prio==='ALL'&&b.dataset.prio==='ALL');
            b.style.opacity   = active ? '1' : '0.5';
            b.style.transform = active ? 'scale(1.05)' : 'scale(1)';
        });
        infoWin.close();
    };

    if (markers.length > 0) {
        const bounds = new google.maps.LatLngBounds();
        markers.forEach(m => bounds.extend(m.getPosition()));
        map.fitBounds(bounds);
        google.maps.event.addListenerOnce(map, 'idle', () => { if (map.getZoom()>16) map.setZoom(16); });
    }
}

window.openEnrich = function(addr) {
    if (window.parent && window.parent.quickLoad) window.parent.quickLoad(addr);
    else alert('Dashboard: analyze ' + addr);
};
window.openProposal = function(addr) {
    if (window.parent && window.parent.openProposalForLead) window.parent.openProposalForLead(addr, 175);
    else alert('Dashboard: proposal for ' + addr);
};
"""
        maps_js = (maps_js
            .replace("__GMAPS_KEY__", google_maps_key)
            .replace("__LAT__",      f"{avg_lat:.6f}")
            .replace("__LNG__",      f"{avg_lng:.6f}")
            .replace("__GEOJSON__",  geojson_json))
        maps_head = maps_head.replace("__GMAPS_KEY__", google_maps_key)

    else:
        # Leaflet fallback
        maps_head = (
            '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>\n'
            '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>'
        )
        maps_js = r"""
const map = L.map('map').setView([__LAT__, __LNG__], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    {attribution:'© OpenStreetMap contributors'}).addTo(map);

const PC = {HOT:'#ef4444', WARM:'#f97316', COOL:'#3b82f6', LOW:'#6b7280'};
const markers = [];
const GEOJSON = __GEOJSON__;

GEOJSON.features.forEach(f => {
    const [lng, lat] = f.geometry.coordinates;
    const p = f.properties;
    const color = PC[p.priority] || '#9ca3af';
    const icon = L.divIcon({
        html: '<div style="background:'+color+';color:#fff;width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;border:3px solid rgba(0,0,0,0.3)">'+p.lead_score+'</div>',
        className: '', iconSize: [34,34], iconAnchor: [17,17],
    });
    const m = L.marker([lat,lng],{icon}).addTo(map);
    const sav = p.annual_savings_yr1_usd ? '$'+p.annual_savings_yr1_usd.toLocaleString()+'/yr' : 'N/A';
    m.bindPopup('<b>'+p.address+'</b><br>Score: '+p.lead_score+'/100 \u00b7 '+p.priority+'<br>Savings: '+sav);
    m.priority = p.priority;
    markers.push(m);
});

window.filterMap = function(prio) {
    markers.forEach(m => {
        if (prio==='ALL'||m.priority===prio) map.addLayer(m);
        else map.removeLayer(m);
    });
    document.querySelectorAll('.filter-btn').forEach(b => {
        b.style.opacity = (b.dataset.prio===prio||(prio==='ALL'&&b.dataset.prio==='ALL')) ? '1' : '0.5';
    });
};
"""
        maps_js = (maps_js
            .replace("__LAT__",     f"{avg_lat:.6f}")
            .replace("__LNG__",     f"{avg_lng:.6f}")
            .replace("__GEOJSON__", geojson_json))

    # ── Final HTML (safe f-string — no JS template literals inside) ──────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Solar Intelligence Suite</title>
{maps_head}
<style>
* {{ margin:0;padding:0;box-sizing:border-box }}
body {{ font-family:'Segoe UI',Arial,sans-serif;background:#0f172a;color:#f9fafb;height:100vh;display:flex;flex-direction:column;overflow:hidden }}
.header {{ background:linear-gradient(90deg,#1e3a5f,#1e1b4b);padding:10px 20px;display:flex;align-items:center;gap:16px;border-bottom:1px solid #334155;flex-shrink:0 }}
.header h1 {{ font-size:18px;font-weight:700;color:#f9fafb }}
.header .sub {{ font-size:12px;color:#94a3b8 }}
.stats-bar {{ display:flex;gap:10px;padding:8px 20px;background:#0f172a;border-bottom:1px solid #1e293b;flex-shrink:0;flex-wrap:wrap }}
.stat-box {{ background:#1e293b;border:1px solid #334155;border-radius:8px;padding:6px 14px;text-align:center;min-width:90px }}
.stat-box .val {{ font-size:18px;font-weight:700 }}
.stat-box .lbl {{ font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px }}
.filter-bar {{ display:flex;gap:8px;padding:8px 20px;background:#0f172a;border-bottom:1px solid #1e293b;flex-shrink:0;align-items:center }}
.filter-bar label {{ font-size:12px;color:#64748b;margin-right:4px }}
.filter-btn {{ padding:5px 14px;border-radius:20px;border:none;cursor:pointer;font-size:12px;font-weight:700;transition:all 0.15s }}
.btn-all  {{ background:#334155;color:#f9fafb }}
.btn-hot  {{ background:#ef4444;color:#fff }}
.btn-warm {{ background:#f97316;color:#fff }}
.btn-cool {{ background:#3b82f6;color:#fff }}
.btn-low  {{ background:#6b7280;color:#fff }}
#map {{ flex:1;width:100% }}
.legend {{ position:absolute;bottom:20px;left:20px;z-index:1000;background:rgba(15,23,42,0.95);border:1px solid #334155;border-radius:10px;padding:12px 16px }}
.legend h4 {{ font-size:12px;color:#94a3b8;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px }}
.legend-item {{ display:flex;align-items:center;gap:8px;margin-bottom:5px;font-size:12px }}
.legend-dot {{ width:14px;height:14px;border-radius:50%;flex-shrink:0 }}
.gen-time {{ font-size:10px;color:#475569;margin-left:auto }}
</style>
</head>
<body>
<div class="header">
  <div>&#9728;&#65039;</div>
  <div><h1>Solar Lead Map</h1><div class="sub">All enriched leads &#8212; color-coded by priority</div></div>
  <div class="gen-time">Generated {gen_time}</div>
</div>
<div class="stats-bar">
  <div class="stat-box"><div class="val" style="color:#60a5fa">{total}</div><div class="lbl">Total Leads</div></div>
  <div class="stat-box"><div class="val" style="color:#ef4444">{hot}</div><div class="lbl">&#128293; HOT</div></div>
  <div class="stat-box"><div class="val" style="color:#f97316">{warm}</div><div class="lbl">&#127780; WARM</div></div>
  <div class="stat-box"><div class="val" style="color:#22c55e">${pipeline:,.0f}</div><div class="lbl">Pipeline/yr</div></div>
</div>
<div class="filter-bar">
  <label>Filter:</label>
  <button class="filter-btn btn-all"  data-prio="ALL"  onclick="filterMap('ALL')">All Leads</button>
  <button class="filter-btn btn-hot"  data-prio="HOT"  onclick="filterMap('HOT')">&#128293; HOT</button>
  <button class="filter-btn btn-warm" data-prio="WARM" onclick="filterMap('WARM')">&#127780; WARM</button>
  <button class="filter-btn btn-cool" data-prio="COOL" onclick="filterMap('COOL')">&#128309; COOL</button>
  <button class="filter-btn btn-low"  data-prio="LOW"  onclick="filterMap('LOW')">&#11036; LOW</button>
  <span style="font-size:11px;color:#475569;margin-left:8px">Click a pin for details</span>
</div>
<div id="map" style="position:relative"></div>
<div class="legend">
  <h4>Priority</h4>
  <div class="legend-item"><div class="legend-dot" style="background:#ef4444"></div> HOT &#8212; 80+ score</div>
  <div class="legend-item"><div class="legend-dot" style="background:#f97316"></div> WARM &#8212; 60-79</div>
  <div class="legend-item"><div class="legend-dot" style="background:#3b82f6"></div> COOL &#8212; 40-59</div>
  <div class="legend-item"><div class="legend-dot" style="background:#6b7280"></div> LOW &#8212; &lt;40</div>
</div>
<script>
{maps_js}
</script>
</body>
</html>"""
    return html


# ─── Save Helper ─────────────────────────────────────────────────────────────

def save_map(html: str, name: str = None) -> str:
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    name = name or f"lead_map_{ts}.html"
    out  = MAPS_DIR / name
    out.write_text(html)
    return str(out)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate an interactive lead map HTML page")
    parser.add_argument("--open",       action="store_true", help="Open in browser after generating")
    parser.add_argument("--print-path", action="store_true", help="Print just the output file path")
    parser.add_argument("--output",     default=None,        help="Custom output path")
    parser.add_argument("--title",      default="Solar Lead Map", help="Map title")
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    leads   = collect_all_leads()
    geojson = leads_to_geojson(leads)
    html    = generate_map_html(geojson, google_maps_key=api_key, title=args.title)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        path = str(out)
    else:
        path = save_map(html)

    if args.print_path:
        print(path)
    else:
        f    = geojson["features"]
        tot  = len(f)
        h    = sum(1 for x in f if x["properties"]["priority"] == "HOT")
        w    = sum(1 for x in f if x["properties"]["priority"] == "WARM")
        pipe = sum(x["properties"]["annual_savings_yr1_usd"] for x in f
                   if x["properties"]["priority"] in ("HOT","WARM"))
        print(f"\n\U0001f5fa\ufe0f  Lead Map Generated")
        print(f"   {tot} leads plotted  |  \U0001f525 {h} HOT  |  \U0001f324\ufe0f {w} WARM  |  \U0001f4b0 ${pipe:,.0f}/yr pipeline")
        print(f"   Saved: {path}")
        if api_key:
            print("   Mode: Google Maps (satellite, custom SVG pins)")
        else:
            print("   Mode: OpenStreetMap (Leaflet fallback)")

    if args.open:
        import subprocess
        subprocess.Popen(["xdg-open", path], stderr=subprocess.DEVNULL)

    return path, geojson


if __name__ == "__main__":
    main()
