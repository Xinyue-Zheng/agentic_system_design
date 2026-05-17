import json

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

target_neighbors = set(['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10', 'USID_37'])
target_sectors = set(['USID_09_S0', 'USID_09_S1', 'USID_09_S2'])

print("Pixels where USID_09 sector is dominant, with no neighbor backup:")
for p in pixels:
    info = p['info']
    dom_id = cell_id(info.get('dominant'))
    b1_id = cell_id(info.get('backup1'))
    b2_id = cell_id(info.get('backup2'))
    if dom_id in target_sectors:
        b1_usid = usid_of(b1_id)
        b2_usid = usid_of(b2_id)
        if b1_usid not in target_neighbors and b2_usid not in target_neighbors:
            print("  hole: lat=%s lon=%s dom=%s b1=%s b2=%s" % (p['lat'], p['lon'], dom_id, b1_id, b2_id))

print("\nAll USID_09_S0 pixels detail:")
for p in pixels:
    info = p['info']
    dom_id = cell_id(info.get('dominant'))
    b1_id = cell_id(info.get('backup1'))
    b2_id = cell_id(info.get('backup2'))
    if dom_id == 'USID_09_S0':
        print("  lat=%s lon=%s b1=%s b2=%s" % (p['lat'], p['lon'], b1_id, b2_id))

print("\nAll USID_09_S2 pixels detail (sample):")
count = 0
for p in pixels:
    info = p['info']
    dom_id = cell_id(info.get('dominant'))
    b1_id = cell_id(info.get('backup1'))
    b2_id = cell_id(info.get('backup2'))
    if dom_id == 'USID_09_S2' and count < 5:
        print("  lat=%s lon=%s b1=%s b2=%s" % (p['lat'], p['lon'], b1_id, b2_id))
        count += 1
