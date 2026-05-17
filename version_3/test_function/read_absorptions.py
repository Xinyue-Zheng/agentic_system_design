import json

with open('/workspace/version_3/artifacts/TKT-2026-04-17-0002_20260505T064118Z/preprocessing_stats.json') as f:
    stats = json.load(f)

per_backup = stats['load_redistribution']['per_backup']
neighbors = ["USID_01", "USID_25", "USID_43", "USID_29", "USID_45", "USID_10"]

print("Absorption fractions for neighbors:")
for nb in neighbors:
    if nb in per_backup:
        d = per_backup[nb]
        print(f"\n{nb}:")
        print(f"  absorption_fraction_of_target: {d['absorption_fraction_of_target']}")
        print(f"  absorption_pixel_count: {d['absorption_pixel_count']}")
        print(f"  handover_quality: {d['handover_quality']}")
        print(f"  overload_risk: {d['overload_risk']}")
        print(f"  post_outage_load_factor: {d['post_outage_load_factor']}")
        print(f"  rsrp_in_zone_mean_dbm: {d['rsrp_in_zone_mean_dbm']}")
    else:
        print(f"\n{nb}: NOT FOUND in per_backup")
        print("  Available keys:", list(per_backup.keys()))

print("\n\nAll per_backup keys:", list(per_backup.keys()))

# Also get coverage hole info and target info
lr = stats['load_redistribution']
print(f"\ntarget_dominant_pixels: {lr['target_dominant_pixels']}")
print(f"coverage_hole_fraction: {lr['coverage_hole_fraction']}")
print(f"primary_backup_usid: {lr['primary_backup_usid']}")

# Check overlap_info
oi = stats['overlap_info']
print("\nOverlap info keys:", list(oi.keys()))
print(json.dumps(oi, indent=2)[:3000])
