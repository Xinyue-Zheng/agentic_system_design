import os, sys, io, base64

os.environ['DATA_DIR'] = 'data'
os.environ['MAP_OUTPUT_DIR'] = 'artifacts/TKT-2026-04-17-0002_20260505T081437Z'

out_dir = 'artifacts/TKT-2026-04-17-0002_20260505T081437Z'

try:
    from staticmap import StaticMap
    print('staticmap available')

    zoom = max(10, min(15, round(14 - (3.0 / 5))))
    print(f'zoom for radius 3km: {zoom}')

    m = StaticMap(800, 800)
    img = m.render(zoom=zoom, center=[-96.694043, 33.027275])
    img.save(f'{out_dir}/geo_map_33.0273_-96.6940_3.0km.png', format='PNG')
    print('S0 centroid map saved')

    m2 = StaticMap(800, 800)
    img2 = m2.render(zoom=zoom, center=[-96.695433, 33.02511])
    img2.save(f'{out_dir}/geo_map_33.0251_-96.6954_3.0km.png', format='PNG')
    print('S2 centroid map saved')

except ImportError as e:
    print(f'staticmap not available: {e}')
    path = os.path.join('data', 'geo_features_map.png')
    print(f'local synthetic map exists: {os.path.exists(path)}')
