#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""Standalone FFT/PSD analysis for a saved CAEN CDCU PMM CSV file.

This utility is intentionally independent of live monitoring.  It accepts a PMM
CSV that was saved by cdcu_monitor.py (initial or fault-triggered), then runs the
same 10 kHz spectral-analysis path used by the live toolkit.

Authored By:
Byron Jordan
Power Supply Engineer
Advanced Photon Source (APS)
Argonne National Laboratory
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

import cdcu_ripple_psd
import cdcu_diagnostics
from cdcu_ripple_bands import BAND_STR

PMM_CHANNELS: Dict[str, tuple[str, str]] = {
    "vout_V": ("V", "PMM Output Voltage"),
    "iout_A": ("A", "PMM Output Current"),
    "iset_A": ("A", "PMM Setpoint Current"),
}


def _parse_channels(raw: str) -> list[str]:
    """Convert a comma-separated channel list into validated PMM column names."""
    # Capture requested here; the next step uses this intermediate result directly.
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    # Store this decision in invalid; later logic uses the same boolean without recomputing it.
    invalid = [item for item in requested if item not in PMM_CHANNELS]
    # Take this branch only when the stated operating condition is true.
    if invalid:
        # Store this decision in valid; later logic uses the same boolean without recomputing it.
        valid = ", ".join(PMM_CHANNELS)
        # Raise a specific error instead of allowing bad input to propagate into the analysis.
        raise ValueError(f"Unknown PMM channel(s): {', '.join(invalid)}. Valid: {valid}")
    # Hand the finished value back to the caller.
    return requested


def _ppm_reference(series: pd.Series, override: Optional[float], *,
                   model: Optional[str], channel: str) -> tuple[Optional[float], str]:
    """Resolve the ppm denominator and state exactly what it represents.

    Explicit operator references take priority. When a CDCU model is supplied,
    output/set current default to rated current and output voltage defaults to
    rated voltage so the result is ppm/FS. Otherwise the channel DC mean is used
    and the result is explicitly labeled ppm of operating point.
    """
    if override is not None and math.isfinite(override) and override != 0.0:
        return float(override), "operator reference"
    spec = cdcu_diagnostics.get_model_spec(model)
    if spec is not None:
        if channel in ("iout_A", "iset_A"):
            return float(spec["rated_A"]), "full scale (rated current)"
        if channel == "vout_V":
            return float(spec["rated_V"]), "full scale (rated voltage)"
    dc = float(pd.to_numeric(series, errors="coerce").mean())
    return (dc, "operating point (DC mean)") if math.isfinite(dc) and dc != 0.0 else (None, "undefined")

def analyze_pmm_csv(
    csv_path: str,
    *,
    outdir: Optional[str] = None,
    channels: Optional[Iterable[str]] = None,
    ppm_refs: Optional[Dict[str, float]] = None,
    load_desc: Optional[str] = None,
    sig_threshold_ppm: float = 12.0,
    fft_y_mode: str = "magnitude",
    model: Optional[str] = None,
) -> Dict[str, dict]:
    """Run FFT, PSD, cumulative RMS, and band analysis on a saved PMM capture."""
    # Resolve the PMM CSV to an absolute path before opening it.
    source = Path(csv_path).expanduser().resolve()
    # Take this branch only when the stated operating condition is true.
    if not source.is_file():
        # Raise a specific error instead of allowing bad input to propagate into the analysis.
        raise FileNotFoundError(f"PMM CSV not found: {source}")

    # Load the source data into a DataFrame for numeric processing.
    try:
        df = pd.read_csv(source)
    except Exception as exc:
        raise ValueError(
            f"Unable to read PMM CSV '{source}'. FFT/PSD accepts saved PMM CSV files only."
        ) from exc
    # Take this branch only when the stated operating condition is true.
    if "time_s" not in df.columns:
        # Raise a specific error instead of allowing bad input to propagate into the analysis.
        raise ValueError(f"PMM CSV must contain 'time_s'. Columns: {list(df.columns)}")

    # Build the channel list that will be processed during this run.
    selected = list(channels or PMM_CHANNELS.keys())
    # Identify requested channels that are not present in the source file.
    missing = [col for col in selected if col not in df.columns]
    # Take this branch only when the stated operating condition is true.
    if missing:
        # Raise a specific error instead of allowing bad input to propagate into the analysis.
        raise ValueError(f"Requested PMM channel(s) not present: {', '.join(missing)}")

    # Resolve the output directory for the standalone PMM analysis.
    destination = Path(outdir).expanduser().resolve() if outdir else source.parent / f"{source.stem}_fft_psd"
    # Create the output directory now so the following writes have a valid destination.
    destination.mkdir(parents=True, exist_ok=True)

    # Resolve the local APS/Argonne branding image used by the report output.
    logo = Path(__file__).resolve().parent / "ANL_RGB-APS-fullname_horiz.png"
    # Capture refs here; the next step uses this intermediate result directly.
    refs = ppm_refs or {}
    # Carry out this step before advancing to the next part of the function.
    results: Dict[str, dict] = {}

    # Walk the collection in order so every item receives the same treatment.
    for col in selected:
        # Carry out this step before advancing to the next part of the function.
        unit, label = PMM_CHANNELS[col]
        # Keep only the time axis and active PMM channel, then remove unusable rows.
        sub = df[["time_s", col]].copy()
        # Capture sub["time_s"] here; the next step uses this intermediate result directly.
        sub["time_s"] = pd.to_numeric(sub["time_s"], errors="coerce")
        # Capture sub[col] here; the next step uses this intermediate result directly.
        sub[col] = pd.to_numeric(sub[col], errors="coerce")
        # Keep only the time axis and active PMM channel, then remove unusable rows.
        sub = sub.dropna().reset_index(drop=True)
        # Make sure enough samples are available before running the calculation.
        if len(sub) < 64:
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise ValueError(f"{col} has only {len(sub)} valid samples; at least 64 are required.")

        # Select the engineering reference used to express ripple in ppm.
        ppm_ref, ppm_ref_label = _ppm_reference(sub[col], refs.get(col), model=model, channel=col)
        # Give each PMM channel its own output directory to keep products separated.
        channel_dir = destination / col
        # Create the output directory now so the following writes have a valid destination.
        channel_dir.mkdir(parents=True, exist_ok=True)
        # Build the composite-report filename for this PMM channel.
        composite = channel_dir / f"{source.stem}_{col}_report.png"

        # Capture results[col] here; the next step uses this intermediate result directly.
        results[col] = cdcu_ripple_psd.analyze_series_for_reports(
            df=sub,
            time_col="time_s",
            value_col=col,
            outdir=str(channel_dir),
            ppm_ref=ppm_ref,
            ppm_ref_label=ppm_ref_label,
            bands=BAND_STR,
            sig_threshold_ppm=float(sig_threshold_ppm),
            label=label,
            quantity_unit=unit,
            window="hann",
            nperseg=cdcu_ripple_psd.recommended_welch_nperseg(len(sub), target=16384),
            overlap=0.5,
            auto_scale_freq=True,
            load_desc=load_desc,
            acq_timestamp=None,
            logo_path=str(logo) if logo.is_file() else None,
            composite_png=str(composite),
            file_prefix=source.stem,
            fft_y_mode=fft_y_mode,
        )

    # Resolve summary_path once so later file operations use the same location.
    summary_path = destination / f"{source.stem}_pmm_fft_summary.txt"
    # Use a context manager so the file or resource is closed cleanly on every exit path.
    with summary_path.open("w", encoding="utf-8") as handle:
        # Write this field to the report in the same order an engineer will review it.
        handle.write(f"PMM source: {source}\n")
        # Write this field to the report in the same order an engineer will review it.
        handle.write(f"Channels: {', '.join(selected)}\n")
        # Write this field to the report in the same order an engineer will review it.
        handle.write(f"Samples: {len(df)}\n")
        # Write this field to the report in the same order an engineer will review it.
        handle.write("\nSpectral results:\n")
        # Walk the collection in order so every item receives the same treatment.
        for col, result in results.items():
            # Write this field to the report in the same order an engineer will review it.
            handle.write(f"\n{col}\n")
            # Write this field to the report in the same order an engineer will review it.
            handle.write(f"  Fs: {result.get('fs_hz', math.nan):.6g} Hz\n")
            # Write this field to the report in the same order an engineer will review it.
            handle.write(f"  ppm reference: {result.get('ppm_ref')} ({result.get('ppm_ref_label', 'unspecified')})\n")
            # Write this field to the report in the same order an engineer will review it.
            handle.write(f"  Integrated RMS: {result.get('integrated_rms')} {result.get('quantity_unit', '')}\n")
            # Capture ppm here; the next step uses this intermediate result directly.
            ppm = result.get("integrated_rms_ppm")
            # Write this field to the report in the same order an engineer will review it.
            handle.write(f"  Integrated RMS: {ppm if ppm is not None else 'N/A'} ppm ({result.get('ppm_ref_label', 'unspecified')})\n")
            handle.write(f"  Parseval check: {result.get('parseval_status', 'N/A')} ({result.get('parseval_error_pct', math.nan):.3f}%)\n")
            _sampling = result.get('sampling_info') or {}
            handle.write(f"  Timing CV(dt): {_sampling.get('dt_cv')} | resampled={_sampling.get('resampled')}\n")

    # Write this status to the console so the operator can follow the run in real time.
    print(f"[cdcu_pmm_fft] Analysis complete: {destination}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"[cdcu_pmm_fft] Summary: {summary_path}")
    # Hand the finished value back to the caller.
    return results


def main() -> int:
    """Parse command-line options and run standalone PMM spectral analysis."""
    # Create the command-line parser for this utility.
    parser = argparse.ArgumentParser(
        description="Run FFT/PSD analysis directly from a saved CDCU PMM CSV."
    )
    # Carry out this step before advancing to the next part of the function.
    parser.add_argument("--csv", required=True, help="PMM CSV from cdcu_monitor.py")
    # Carry out this step before advancing to the next part of the function.
    parser.add_argument("--outdir", default=None, help="Output directory; default is beside the PMM CSV")
    # Carry out this step before advancing to the next part of the function.
    parser.add_argument(
        "--channels",
        default="vout_V,iout_A",
        help="Comma-separated PMM columns to analyze (default excludes inactive Set Current spectral page)",
    )
    # Carry out this step before advancing to the next part of the function.
    parser.add_argument("--vout-ref", type=float, default=None, help="Vout ppm reference in volts")
    # Carry out this step before advancing to the next part of the function.
    parser.add_argument("--iout-ref", type=float, default=None, help="Iout ppm reference in amperes")
    # Carry out this step before advancing to the next part of the function.
    parser.add_argument("--iset-ref", type=float, default=None, help="Iset ppm reference in amperes")
    # Carry out this step before advancing to the next part of the function.
    parser.add_argument("--load-desc", default=None, help="Optional load/magnet description for report labeling")
    parser.add_argument("--model", choices=("CDCU-100", "CDCU-200", "CDCU-300"), default=None, help="CDCU model; enables automatic ppm/FS references for PMM output/set current and output voltage")
    # Carry out this step before advancing to the next part of the function.
    parser.add_argument("--sig-threshold-ppm", type=float, default=12.0, help="Significant spectral-component threshold")
    # Let the operator choose whether the primary filled FFT reports physical magnitude, percent, or ppm.
    parser.add_argument("--fft-y", choices=("magnitude", "percent", "ppm"), default="magnitude", help="Primary FFT Y-axis: magnitude, percent, or ppm")
    # Parse the command-line settings supplied by the operator.
    args = parser.parse_args()

    # Collect the optional user-supplied ppm references by PMM channel.
    ppm_refs = {
        "vout_V": args.vout_ref,
        "iout_A": args.iout_ref,
        "iset_A": args.iset_ref,
    }
    # Carry out this step before advancing to the next part of the function.
    analyze_pmm_csv(
        args.csv,
        outdir=args.outdir,
        channels=_parse_channels(args.channels),
        ppm_refs=ppm_refs,
        load_desc=args.load_desc,
        sig_threshold_ppm=args.sig_threshold_ppm,
        fft_y_mode=args.fft_y,
        model=args.model,
    )
    # Hand the finished value back to the caller.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
