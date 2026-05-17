import sys, os, json
sys.path.insert(0, '.')
os.environ['DATA_DIR'] = 'data'
os.environ['MAP_OUTPUT_DIR'] = 'artifacts/TKT-2026-04-17-0002_20260505T075652Z'
from mcp_server.server import get_coverage_pixels_by_sector

for sid in ['USID_09_S0', 'USID_09_S2']:
    pixels = get_coverage_pixels_by_sector(sid)
    dom_pixels = [p for p in pixels if p['info'].get('dominant', '').startswith(sid)]
    lats = [p['lat'] for p in dom_pixels]
    lons = [p['lon'] for p in dom_pixels]
    print(f"{sid}: total={len(pixels)}, dominant={len(dom_pixels)}")
    if dom_pixels:
        print(f"  lat_min={min(lats):.6f}, lat_max={max(lats):.6f}")
        print(f"  lon_min={min(lons):.6f}, lon_max={max(lons):.6f}")
        print(f"  centroid_lat={sum(lats)/len(lats):.6f}, centroid_lon={sum(lons)/len(lons):.6f}")
        backups = {}
        for p in dom_pixels:
            b1 = p['info'].get('backup1', '')
            if b1:
                backups[b1] = backups.get(b1, 0) + 1
        print(f"  backup1 counts: {backups}")
    print()
