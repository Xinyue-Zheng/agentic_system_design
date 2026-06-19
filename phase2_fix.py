#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 2 ONLY -- recovery version.

Reads the existing bucket files produced by phase 1 and writes the final
output. Tolerant of rows with varying field counts (source CSVs had
different column counts, e.g. 880 vs 884), so it will NOT crash like the
pandas reader and will NOT drop any rows.

Key facts it relies on:
  - "__order" is always the LAST field of every row (it was appended last
    in phase 1, regardless of the row's width).
  - The eNodeB column sits at a fixed position counted from the LEFT
    (taken from the header line).

It parses each line with the csv module (so quoted commas are handled
correctly) only to extract the two sort keys, but writes back the original
line with just the trailing __order field removed -- preserving each row's
content exactly.
"""

import os
import csv

# ============================================================
# CONFIG -- match these to your phase-1 run
# ============================================================

TMP_DIR = "<TMP_DIR>"          # folder with bucket_XXXX.csv from phase 1
OUTPUT_DIR = "<OUTPUT_DIR>"    # where final files go
ENB_COL = "<ENB_COLUMN_NAME>"  # same eNodeB column name as before

# ============================================================


def fix_one_bucket(bpath, out_path):
    with open(bpath, "r", encoding="utf-8", newline="") as f:
        header = f.readline().rstrip("\n").rstrip("\r")
        if not header:
            return 0  # empty bucket

        header_fields = next(csv.reader([header]))
        try:
            enb_idx = header_fields.index(ENB_COL)
        except ValueError:
            raise ValueError(
                f"Column '{ENB_COL}' not found in header of {bpath}"
            )
        # Sanity check: last column should be the helper column
        if header_fields[-1] != "__order":
            print(f"[WARN] last column is '{header_fields[-1]}', expected '__order' in {bpath}")

        rows = []  # (enb, order, line_without_order)
        for raw in f:
            line = raw.rstrip("\n").rstrip("\r")
            if not line:
                continue
            # Parse just to read the keys safely (handles quoted commas)
            fields = next(csv.reader([line]))
            enb = fields[enb_idx]
            try:
                order = int(fields[-1])
            except ValueError:
                order = 0  # fallback if a row's last field isn't an int
            # Drop the trailing __order field from the raw line for output.
            # __order is an unquoted int, so rsplit on the last comma is safe.
            line_wo_order = line.rsplit(",", 1)[0]
            rows.append((enb, order, line_wo_order))

    # Stable sort: same eNodeB grouped, chronological (__order) within a group
    rows.sort(key=lambda r: (r[0], r[1]))

    header_wo_order = header.rsplit(",", 1)[0]
    with open(out_path, "w", encoding="utf-8", newline="") as out:
        out.write(header_wo_order + "\n")
        for _, _, line in rows:
            out.write(line + "\n")

    enb_count = len({r[0] for r in rows})
    return enb_count, len(rows)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    bucket_files = sorted(
        fn for fn in os.listdir(TMP_DIR) if fn.startswith("bucket_") and fn.endswith(".csv")
    )

    out_count = 0
    for fn in bucket_files:
        bpath = os.path.join(TMP_DIR, fn)
        if os.path.getsize(bpath) == 0:
            continue
        b_id = fn[len("bucket_"):-len(".csv")]
        out_path = os.path.join(OUTPUT_DIR, f"enodeb_group_{b_id}.csv")
        result = fix_one_bucket(bpath, out_path)
        if result == 0:
            continue
        enb_count, n_rows = result
        out_count += 1
        print(f"[Phase 2] Wrote: {out_path}  ({enb_count} eNodeBs, {n_rows} rows)")

    print(f"[DONE] Generated {out_count} output files")


if __name__ == "__main__":
    main()
