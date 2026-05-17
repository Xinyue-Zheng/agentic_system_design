import json
import statistics

with open('data/usid_coverage_pixels.json') as f:
    data = json.load(f)

pixels = data['pixels']

def cell_id(cell):
    if cell is None:
        return None
    return cell.get('ID')

def usid_of(sector_id):
    if sector_id is None:
        return None
    parts = sector_id.split('_')
    return parts[0] + '_' + parts[1]

def get_pixels_by_sector(sector_id):
    result = []
    for p in pixels:
        info = p['info']
        if (cell_id(info.get('dominant')) == sector_id or
            cell_id(info.get('backup1')) == sector_id or
            cell_id(info.get('backup2')) == sector_id):
            result.append(p)
    return result

target_neighbors = set(['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10', 'USID_37'])

for sector in ['USID_09_S0', 'USID_09_S2']:
    px = get_pixels_by_sector(sector)
    print("\n=== %s: %d pixels ===" % (sector, len(px)))

    lats = [p['lat'] for p in px]
    lons = [p['lon'] for p in px]
    print("  bbox: lat %.6f-%.6f, lon %.6f-%.6f" % (min(lats), max(lats), min(lons), max(lons)))
    print("  centroid: lat %.6f, lon %.6f" % (sum(lats)/len(lats), sum(lons)/len(lons)))

    print("  Per-backup RSRP in zone (primary only - neighbor cells):")
    backup_rsrp = {}
    for p in px:
        info = p['info']
        dom_id = cell_id(info.get('dominant'))
        dom_usid = usid_of(dom_id)
        dom_rsrp = info.get('dominant', {}).get('rsrp', None) if info.get('dominant') else None

        if dom_usid in target_neighbors and dom_usid != 'USID_09' and dom_rsrp is not None:
            if dom_usid not in backup_rsrp:
                backup_rsrp[dom_usid] = []
            backup_rsrp[dom_usid].append(dom_rsrp)

    for usid, rsrps in sorted(backup_rsrp.items(), key=lambda x: -len(x[1])):
        p50 = statistics.median(rsrps)
        print("    %s: %d dominant pixels, rsrp_p50=%.2f dBm" % (usid, len(rsrps), p50))

print("\n=== Coverage hole pixel detail ===")
for p in pixels:
    info = p['info']
    dom_id = cell_id(info.get('dominant'))
    b1_id = cell_id(info.get('backup1'))
    b2_id = cell_id(info.get('backup2'))
    if dom_id in ['USID_09_S0', 'USID_09_S1', 'USID_09_S2'] and b1_id is None and b2_id is None:
        print("  HOLE: lat=%.6f lon=%.6f dom=%s" % (p['lat'], p['lon'], dom_id))
        print("  USID_09 tower: lat=33.026668, lon=-96.694455")
        dlat = p['lat'] - 33.026668
        dlon = p['lon'] - (-96.694455)
        print("  Offset from tower: dlat=%.6f, dlon=%.6f" % (dlat, dlon))
