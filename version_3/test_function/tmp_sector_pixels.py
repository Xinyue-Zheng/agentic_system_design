import json

with open('data/usid_coverage_pixels.json') as f:
    data = json.load(f)

pixels = data['pixels']

s0_pixels = []
s2_pixels = []

for px in pixels:
    dom = px['info']['dominant']
    if dom['ID'] == 'USID_09_S0':
        s0_pixels.append({'lat': px['lat'], 'lon': px['lon']})
    elif dom['ID'] == 'USID_09_S2':
        s2_pixels.append({'lat': px['lat'], 'lon': px['lon']})

print('USID_09_S0 dominant pixels:', len(s0_pixels))
for p in s0_pixels:
    print(' ', p)

print()
print('USID_09_S2 dominant pixels:', len(s2_pixels))
for p in s2_pixels:
    print(' ', p)

print()
if s0_pixels:
    lats0 = [p['lat'] for p in s0_pixels]
    lons0 = [p['lon'] for p in s0_pixels]
    print('S0 bbox: lat', min(lats0), '-', max(lats0), 'lon', min(lons0), '-', max(lons0))
    print('S0 centroid: lat', round(sum(lats0)/len(lats0),6), 'lon', round(sum(lons0)/len(lons0),6))

if s2_pixels:
    lats2 = [p['lat'] for p in s2_pixels]
    lons2 = [p['lon'] for p in s2_pixels]
    print('S2 bbox: lat', min(lats2), '-', max(lats2), 'lon', min(lons2), '-', max(lons2))
    print('S2 centroid: lat', round(sum(lats2)/len(lats2),6), 'lon', round(sum(lons2)/len(lons2),6))
