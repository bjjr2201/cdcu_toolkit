#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""
cdcu_ripple_io.py   (renamed from ps_ripple_io.py)

Read/write helpers for PS_RIPPLE_CSV v1 files produced by cdcu_monitor.py.

Changes from ps_ripple_io.py:
- Imports TIME_COL and CDCU_SIGNAL_COLS from cdcu_ripple_bands so column
  names are defined in one place only.
- read_ps_ripple_metadata() is unchanged.
- write_ps_ripple_csv() is unchanged in behaviour; column awareness is
  now via cdcu_ripple_bands constants rather than hard-coded strings.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Dict, Mapping, Optional, Sequence

# Shared column/band definitions
from cdcu_ripple_bands import TIME_COL, CDCU_SIGNAL_COLS  # noqa: F401  (re-exported for callers)


def read_ps_ripple_metadata(csv_path: str) -> Dict[str, str]:
    """
    Read '# key = value' metadata lines from the top of a PS_RIPPLE_CSV v1 file.
    Stops at the first non-comment line.
    """
    # Carry out this step before advancing to the next part of the function.
    meta: Dict[str, str] = {}
    # Use a context manager so the file or resource is closed cleanly on every exit path.
    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        # Walk the collection in order so every item receives the same treatment.
        for line in f:
            # Take this branch only when the stated operating condition is true.
            if not line.startswith("#"):
                # The required item is resolved, so leave this loop now.
                break
            # Capture s here; the next step uses this intermediate result directly.
            s = line[1:].strip()
            # Take this branch only when the stated operating condition is true.
            if "=" not in s:
                # Skip this item and continue with the next valid candidate.
                continue
            # Carry out this step before advancing to the next part of the function.
            k, v = s.split("=", 1)
            # Capture meta[k.strip()] here; the next step uses this intermediate result directly.
            meta[k.strip()] = v.strip()
    # Hand the finished value back to the caller.
    return meta


def write_ps_ripple_csv(
    path: str,
    time_s: Sequence[float],
    data_cols: Mapping[str, Sequence[float]],
    meta: Optional[Dict[str, str]] = None,
) -> None:
    """
    Write PS_RIPPLE_CSV v1:
      - metadata as '# key = value'
      - blank separator line
      - header row and numeric data rows

    All data columns must have the same length as time_s.
    """
    # Resolve out_dir once so later file operations use the same location.
    out_dir = os.path.dirname(path)
    # Take this branch only when the stated operating condition is true.
    if out_dir:
        # Create the output directory now so the following writes have a valid destination.
        os.makedirs(out_dir, exist_ok=True)

    # Capture n here; the next step uses this intermediate result directly.
    n = len(time_s)
    # Walk the collection in order so every item receives the same treatment.
    for k, col in data_cols.items():
        # Make sure enough samples are available before running the calculation.
        if len(col) != n:
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise ValueError(f"Column '{k}' length {len(col)} != time length {n}")

    # UTF-8 BOM so Excel reads units/degree symbol correctly
    # Use a context manager so the file or resource is closed cleanly on every exit path.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        # Write this field to the report in the same order an engineer will review it.
        f.write("# FORMAT = PS_RIPPLE_CSV v1\n")
        # Write this field to the report in the same order an engineer will review it.
        f.write(f"# created_utc = {datetime.now(timezone.utc).isoformat()}\n")
        # Take this branch only when the stated operating condition is true.
        if meta:
            # Walk the collection in order so every item receives the same treatment.
            for k, v in meta.items():
                # Write this field to the report in the same order an engineer will review it.
                f.write(f"# {k} = {v}\n")
        # Write this field to the report in the same order an engineer will review it.
        f.write("\n")

        # Capture w here; the next step uses this intermediate result directly.
        w = csv.writer(f)
        # Capture header here; the next step uses this intermediate result directly.
        header = ["time_s"] + list(data_cols.keys())
        # Carry out this step before advancing to the next part of the function.
        w.writerow(header)

        # Walk the collection in order so every item receives the same treatment.
        for i in range(n):
            # Capture row here; the next step uses this intermediate result directly.
            row = [f"{float(time_s[i]):.9f}"]
            # Walk the collection in order so every item receives the same treatment.
            for k in data_cols.keys():
                # Add this observation to the ordered history so the sequence is preserved.
                row.append(f"{float(data_cols[k][i]):.12e}")
            # Carry out this step before advancing to the next part of the function.
            w.writerow(row)

    # Write this status to the console so the operator can follow the run in real time.
    print(f"[cdcu_ripple_io] wrote {path}")
