import sys
sys.path.insert(0, 'mcp_server')
import os
os.environ['DATA_DIR'] = 'data'
from server import get_geo_features
import json, base64

result_s2 = get_geo_features(lat=33.024338, lon=-96.695382, radius_km=3.0)
print('S2 source:', result_s2['source'])
print('S2 image_b64 len:', len(result_s2['image_base64']))

result_s0 = get_geo_features(lat=33.027275, lon=-96.694043, radius_km=3.0)
print('S0 source:', result_s0['source'])
print('S0 image_b64 len:', len(result_s0['image_base64']))

with open('artifacts/TKT-2026-04-17-0002_20260505T071533Z/geo_map_s0.png', 'wb') as f:
    f.write(base64.b64decode(result_s0['image_base64']))

with open('artifacts/TKT-2026-04-17-0002_20260505T071533Z/geo_map_s2.png', 'wb') as f:
    f.write(base64.b64decode(result_s2['image_base64']))

print('Maps saved.')
