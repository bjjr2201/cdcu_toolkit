#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------

"""Compatibility launcher for CDCU spectral analysis.

FFT and PSD calculations in the CDCU toolkit are intentionally restricted to
hardware-timed PMM captures.  Live Ethernet polling remains useful for slow
trending, power balance, efficiency, and fault-state diagnostics, but its
sequential timing is not used as a spectral data source.

This file is retained so older operator commands do not disappear.  It simply
routes a saved PMM CSV to cdcu_pmm_fft.py.
"""

from __future__ import annotations

import argparse
from cdcu_pmm_fft import analyze_pmm_csv


def main() -> int:
    """Route a saved PMM CSV to the PMM-only FFT/PSD analysis path."""
    # Define only PMM-safe options; live-polling CSVs are not accepted here.
    parser = argparse.ArgumentParser(
        description=(
            "Compatibility launcher: FFT/PSD is restricted to hardware-timed "
            "PMM CSV files."
        )
    )
    # Require an explicit PMM file so the source of the spectrum is unambiguous.
    parser.add_argument("--csv", required=True, help="Saved PMM CSV containing time_s and PMM channels")
    # Keep output placement operator-selectable for bench and field workflows.
    parser.add_argument("--outdir", default=None, help="Optional PMM analysis output directory")
    # Model identification enables full-scale ppm references for current and voltage.
    parser.add_argument("--model", choices=("CDCU-100", "CDCU-200", "CDCU-300"), default=None)
    # Parse the operator's command-line values before starting the analysis.
    args = parser.parse_args()
    # Run the same PMM analysis engine used by the dedicated standalone utility.
    analyze_pmm_csv(csv_path=args.csv, outdir=args.outdir, model=args.model)
    # Return success only after the PMM analysis completes without an exception.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
