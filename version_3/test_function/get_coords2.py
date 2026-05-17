import json

with open('artifacts/TKT-2026-04-17-0002_20260505T081437Z/preprocessing_stats.json') as f:
    stats = json.load(f)

usids_of_interest = ['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10', 'USID_09']

for usid in usids_of_interest:
    if 'neighbor_profiles' in stats:
        for np in stats['neighbor_profiles']:
            if np.get('usid') == usid:
                print(f"{usid}: lat={np.get('tower_lat')}, lon={np.get('tower_lon')}")
                break
    if 'target_profile' in stats and stats['target_profile'].get('usid') == usid:
        tp = stats['target_profile']
        print(f"{usid} (target): lat={tp.get('tower_lat')}, lon={tp.get('tower_lon')}")

keys = list(stats.keys())[:20]
print("Top-level keys:", keys)
