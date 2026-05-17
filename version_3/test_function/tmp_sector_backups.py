import json

with open('data/usid_coverage_pixels.json') as f:
    data = json.load(f)

pixels = data['pixels']

print("=== USID_09_S0 dominant pixels and their backups ===")
for px in pixels:
    dom = px['info']['dominant']
    if dom['ID'] == 'USID_09_S0':
        b1 = px['info']['backup1']
        b2 = px['info']['backup2']
        print(f"  lat={px['lat']}, lon={px['lon']}")
        print(f"    dominant: {dom['ID']}, rsrp={dom['rsrp']}")
        print(f"    backup1: {b1['ID'] if b1 else None}, rsrp={b1['rsrp'] if b1 else None}")
        print(f"    backup2: {b2['ID'] if b2 else None}, rsrp={b2['rsrp'] if b2 else None}")

print()
print("=== USID_09_S2 dominant pixels and their backups ===")
for px in pixels:
    dom = px['info']['dominant']
    if dom['ID'] == 'USID_09_S2':
        b1 = px['info']['backup1']
        b2 = px['info']['backup2']
        print(f"  lat={px['lat']}, lon={px['lon']}")
        print(f"    dominant: {dom['ID']}, rsrp={dom['rsrp']}")
        print(f"    backup1: {b1['ID'] if b1 else None}, rsrp={b1['rsrp'] if b1 else None}")
        print(f"    backup2: {b2['ID'] if b2 else None}, rsrp={b2['rsrp'] if b2 else None}")
