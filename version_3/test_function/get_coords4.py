import json, statistics

with open('data/usid_coverage_pixels.json') as f:
    cov = json.load(f)

usids_of_interest = ['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10', 'USID_09']

dom_pixels = {u: [] for u in usids_of_interest}
for pixel in cov['pixels']:
    dom = pixel['info'].get('dominant')
    if dom:
        usid_base = dom['ID'].rsplit('_S', 1)[0]
        if usid_base in usids_of_interest:
            dom_pixels[usid_base].append((pixel['lat'], pixel['lon']))

print("Dominant pixel centroids (proxy for tower area):")
for usid, pixels in dom_pixels.items():
    if pixels:
        lats = [p[0] for p in pixels]
        lons = [p[1] for p in pixels]
        print(f"  {usid}: count={len(pixels)}, lat_range=[{min(lats):.4f},{max(lats):.4f}], lon_range=[{min(lons):.4f},{max(lons):.4f}]")
    else:
        print(f"  {usid}: no dominant pixels found")
