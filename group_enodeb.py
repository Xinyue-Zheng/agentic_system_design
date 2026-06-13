#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Merge and group CSV files by eNodeB across multiple months and days.

Strategy: two-phase processing. The full dataset (tens of GB) is never
loaded into memory at once.
  Phase 1 -- Read every source CSV exactly once, routing rows to N
             temporary bucket files keyed by eNodeB.
  Phase 2 -- Load each bucket (now ~1/N of the data) into memory, sort
             by eNodeB so rows of the same eNodeB sit together, then
             write the final output.

Each output CSV holds 100 eNodeBs. All rows of a given eNodeB (across all
days and months) are contiguous and kept in stable file-traversal order
(approximately chronological).
"""

import os
import glob
import math
import shutil
import pandas as pd

# ============================================================
# CONFIG -- only edit this section
# ============================================================

# Root folder (contains the per-month subfolders)
ROOT_DIR = "<ROOT_DIR>"

# Month subfolder names to process (must match the subfolder names)
MONTHS = ["<MONTH_1>", "<MONTH_2>", "<MONTH_3>"]

# eNodeBs to keep (~3000).
# Option A: write them inline as a list below.
# Option B: load from a file, see ENODEB_LIST_FILE.
WANTED_ENODEBS = [
    # "100001", "100002", ...
]
# If the eNodeB list lives in a file (one per line), set the path here.
# When set, it overrides WANTED_ENODEBS above.
ENODEB_LIST_FILE = None  # e.g. "<ENODEB_LIST_FILE>"

# Name of the column that identifies the eNodeB in the CSV
ENB_COL = "<ENB_COLUMN_NAME>"

# How many eNodeBs go into each output file
ENB_PER_FILE = 100

# Output directory
OUTPUT_DIR = "<OUTPUT_DIR>"

# Temp directory (intermediate bucket files from phase 1; removed at the end)
TMP_DIR = "<TMP_DIR>"

# Rows per chunk when streaming (larger = faster but more memory)
CHUNKSIZE = 500_000

# Filename pattern for each daily CSV
FILE_GLOB = "*.csv"

# ============================================================
# Usually no need to edit below
# ============================================================


def load_enodeb_list():
    """Return (ordered eNodeB list, eNodeB -> bucket id map, bucket count)."""
    if ENODEB_LIST_FILE:
        with open(ENODEB_LIST_FILE, "r", encoding="utf-8") as f:
            enbs = [line.strip() for line in f if line.strip()]
    else:
        enbs = [str(e).strip() for e in WANTED_ENODEBS if str(e).strip()]

    if not enbs:
        raise ValueError("eNodeB list is empty; check WANTED_ENODEBS or ENODEB_LIST_FILE")

    # Deduplicate while preserving order
    seen = set()
    ordered = []
    for e in enbs:
        if e not in seen:
            seen.add(e)
            ordered.append(e)

    # Slice into buckets of ENB_PER_FILE; simple, stable contiguous grouping
    enb_to_bucket = {e: (i // ENB_PER_FILE) for i, e in enumerate(ordered)}
    num_buckets = math.ceil(len(ordered) / ENB_PER_FILE)
    return ordered, enb_to_bucket, num_buckets


def iter_input_files():
    """Yield (file_index, path) in month then filename order.

    file_index is used as a stable sort key later.
    """
    idx = 0
    for month in MONTHS:
        month_dir = os.path.join(ROOT_DIR, month)
        if not os.path.isdir(month_dir):
            print(f"[WARN] Month folder not found, skipping: {month_dir}")
            continue
        for path in sorted(glob.glob(os.path.join(month_dir, FILE_GLOB))):
            yield idx, path
            idx += 1


def phase1_partition(wanted_set, enb_to_bucket, num_buckets):
    """Phase 1: read every source CSV once, routing rows to bucket files."""
    os.makedirs(TMP_DIR, exist_ok=True)
    bucket_paths = [os.path.join(TMP_DIR, f"bucket_{b:04d}.csv") for b in range(num_buckets)]

    # Open N write handles once for the whole pass
    handles = [open(p, "w", encoding="utf-8", newline="") for p in bucket_paths]
    header_written = [False] * num_buckets

    try:
        for file_idx, path in iter_input_files():
            # Force the eNodeB column to string so leading zeros are preserved
            reader = pd.read_csv(
                path,
                chunksize=CHUNKSIZE,
                dtype={ENB_COL: str},
            )
            for chunk in reader:
                # Keep only the eNodeBs we care about
                chunk = chunk[chunk[ENB_COL].isin(wanted_set)]
                if chunk.empty:
                    continue
                # Inject sort helper column: traversal order ~= chronological
                chunk["__order"] = file_idx
                # Compute the target bucket for each row
                buckets = chunk[ENB_COL].map(enb_to_bucket)
                for bucket_id, sub in chunk.groupby(buckets):
                    sub.to_csv(
                        handles[bucket_id],
                        header=not header_written[bucket_id],
                        index=False,
                    )
                    header_written[bucket_id] = True
            print(f"[Phase 1] Processed: {path}")
    finally:
        for h in handles:
            h.close()

    return bucket_paths


def phase2_sort_and_write(bucket_paths):
    """Phase 2: load each bucket, sort by eNodeB, write final output."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_count = 0
    for b, bpath in enumerate(bucket_paths):
        if not os.path.exists(bpath) or os.path.getsize(bpath) == 0:
            continue  # This bucket has no data (none of its 100 eNodeBs appeared)
        df = pd.read_csv(bpath, dtype={ENB_COL: str})
        # Stable sort: same eNodeB rows grouped, chronological order within a group
        df = df.sort_values([ENB_COL, "__order"], kind="stable")
        df = df.drop(columns="__order")
        out_path = os.path.join(OUTPUT_DIR, f"enodeb_group_{b:04d}.csv")
        df.to_csv(out_path, index=False)
        out_count += 1
        print(f"[Phase 2] Wrote: {out_path}  ({df[ENB_COL].nunique()} eNodeBs, {len(df)} rows)")
    print(f"[DONE] Generated {out_count} output files")


def main():
    ordered, enb_to_bucket, num_buckets = load_enodeb_list()
    wanted_set = set(ordered)
    print(f"[CONFIG] {len(ordered)} eNodeBs total, split into {num_buckets} output files")

    bucket_paths = phase1_partition(wanted_set, enb_to_bucket, num_buckets)
    phase2_sort_and_write(bucket_paths)

    # Clean up temporary bucket files
    shutil.rmtree(TMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
