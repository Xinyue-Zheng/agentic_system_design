import json

with open('/workspace/version_3/artifacts/TKT-2026-04-17-0002_20260505T064118Z/preprocessing_stats.json') as f:
    stats = json.load(f)

print("Top-level keys:", list(stats.keys()))

# Look for absorption fractions
for key in stats.keys():
    val = stats[key]
    if isinstance(val, dict):
        print(f"\n--- {key} ---")
        sub_keys = list(val.keys())
        print("Sub-keys:", sub_keys[:10])
        if any('USID' in str(k) for k in sub_keys):
            for subk, subv in val.items():
                if 'USID' in str(subk):
                    print(f"  {subk}:", subv)
        elif len(sub_keys) <= 20:
            print(json.dumps(val, indent=2)[:2000])
