import json

with open('artifacts/TKT-2026-04-17-0002_20260506T184755Z/preprocessing_stats.json') as f:
    stats = json.load(f)

lr = stats.get('load_redistribution', {})
print(json.dumps(lr, indent=2))
