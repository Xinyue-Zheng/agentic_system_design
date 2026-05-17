import json

with open('data/usid_coverage_pixels.json') as f:
    cov = json.load(f)

usids_of_interest = ['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10', 'USID_09']

tower_coords = {}
for pixel in cov['pixels']:
    dom = pixel['info'].get('dominant')
    if dom:
        usid_base = dom['ID'].rsplit('_S', 1)[0]
        if usid_base in usids_of_interest and usid_base not in tower_coords:
            if 'tower_lat' in pixel['info'] or 'tower_lat' in dom:
                pass
    if 'tower_lat' in pixel:
        usid_base = pixel['info']['dominant']['ID'].rsplit('_S',1)[0] if pixel['info'].get('dominant') else None
        if usid_base in usids_of_interest:
            tower_coords[usid_base] = (pixel['tower_lat'], pixel['tower_lon'])

print("From pixel tower_lat:", tower_coords)
print()
print("Pixel keys sample:", list(cov['pixels'][0].keys()))
print("Info keys sample:", list(cov['pixels'][0]['info'].keys()))
