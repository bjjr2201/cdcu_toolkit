#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""DCBus input-voltage/current FFT/PSD analysis for hardware-timed captures.

This module deliberately DOES NOT synthesize a 10 kHz record from normal
Ethernet polling.  A valid spectral capture must contain exactly 100,001
samples acquired at 10 kHz (100 us/sample), matching the PMM record length.

Expected channels
-----------------
    dcbus_v_V   DC-Bus input voltage [V]  (MRP)
    dcbus_i_A   DC-Bus input current [A]  (MGPC)

Accepted aliases include MRP and MGPC.

The documented CDCU PMM exposes only output voltage, output current, and
setpoint current.  Therefore this analyzer is acquisition-backend agnostic:
it can analyze a hardware-timed DCBus capture supplied by an external DAQ or a
future/vendor high-speed CDCU interface without pretending that sequential
MRP/MGPC Ethernet polling is a 10 kHz acquisition.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

import cdcu_ripple_psd
from cdcu_ripple_bands import BAND_STR
from cdcu_scope_fft import ScopeChannel, analyze_scope_dataframe

DCBUS_FS_HZ = 10_000.0
DCBUS_DT_S = 1.0 / DCBUS_FS_HZ
DCBUS_N_SAMPLES = 100_001
DCBUS_DURATION_S = (DCBUS_N_SAMPLES - 1) / DCBUS_FS_HZ  # exactly 10.0000 s span
TIMING_CV_LIMIT = 1.0e-4
TIMING_MEAN_REL_TOL = 5.0e-3

CHANNELS = {
    "dcbus_v_V": ("V", "DCBus Input Voltage"),
    "dcbus_i_A": ("A", "DCBus Input Current"),
}

ALIASES = {
    "MRP": "dcbus_v_V",
    "PS:DCBusVoltM": "dcbus_v_V",
    "DCBusVoltM": "dcbus_v_V",
    "dcbus_voltage_V": "dcbus_v_V",
    "Vbus": "dcbus_v_V",
    "MGPC": "dcbus_i_A",
    "PS:DCBusCurrM": "dcbus_i_A",
    "DCBusCurrM": "dcbus_i_A",
    "dcbus_current_A": "dcbus_i_A",
    "Ibus": "dcbus_i_A",
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map common CDCU/EPICS names to the two canonical DCBus columns."""
    rename = {}
    for src, dst in ALIASES.items():
        if src in df.columns and dst not in df.columns:
            rename[src] = dst
    return df.rename(columns=rename)


def validate_dcbus_capture(
    df: pd.DataFrame,
    *,
    assume_10khz_when_no_time: bool = False,
) -> pd.DataFrame:
    """Validate and normalize an exact 100,001-sample / 10 kHz DCBus capture.

    The FFT path is intentionally strict.  It rejects short records, resampled
    live polling, and irregular timestamps rather than manufacturing a uniform
    time base for data that were not acquired uniformly.
    """
    out = _normalize_columns(df.copy())
    missing = [c for c in CHANNELS if c not in out.columns]
    if missing:
        raise ValueError(
            "DCBus capture is missing required channel(s): " + ", ".join(missing)
            + ". Accepted aliases include MRP and MGPC."
        )
    if len(out) != DCBUS_N_SAMPLES:
        raise ValueError(
            f"DCBus spectral capture must contain exactly {DCBUS_N_SAMPLES:,} samples; "
            f"received {len(out):,}."
        )

    for col in CHANNELS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
        if out[col].isna().any():
            raise ValueError(f"DCBus channel {col} contains non-numeric/NaN samples.")

    if "time_s" not in out.columns:
        if not assume_10khz_when_no_time:
            raise ValueError(
                "DCBus capture has no time_s column. Supply hardware timestamps, or use "
                "assume_10khz_when_no_time=True only when the acquisition hardware is known "
                "to have sampled at exactly 10 kHz."
            )
        out.insert(0, "time_s", np.arange(DCBUS_N_SAMPLES, dtype=float) / DCBUS_FS_HZ)
    else:
        t = pd.to_numeric(out["time_s"], errors="coerce").to_numpy(dtype=float)
        if not np.all(np.isfinite(t)):
            raise ValueError("time_s contains invalid timestamps.")
        dt = np.diff(t)
        if len(dt) == 0 or np.any(dt <= 0):
            raise ValueError("time_s must be strictly increasing.")
        mean_dt = float(np.mean(dt))
        cv_dt = float(np.std(dt) / mean_dt) if mean_dt else math.inf
        rel_err = abs(mean_dt - DCBUS_DT_S) / DCBUS_DT_S
        if rel_err > TIMING_MEAN_REL_TOL:
            raise ValueError(
                f"Mean sample interval is {mean_dt:.9g} s, not 100 us (10 kHz). "
                f"Relative error={rel_err:.3%}."
            )
        if cv_dt > TIMING_CV_LIMIT:
            raise ValueError(
                f"DCBus timing is too irregular for PMM-equivalent FFT/PSD: "
                f"CV(dt)={cv_dt:.6g} > {TIMING_CV_LIMIT:.6g}."
            )
        out["time_s"] = t - t[0]

    return out[["time_s", "dcbus_v_V", "dcbus_i_A"]]


def analyze_dcbus_dataframe(
    df: pd.DataFrame,
    *,
    outdir: str,
    prefix: str = "dcbus",
    vbus_ref: Optional[float] = None,
    ibus_ref: Optional[float] = None,
    load_desc: Optional[str] = None,
    acq_timestamp: Optional[str] = None,
    logo_path: Optional[str] = None,
    sig_threshold_ppm: float = 12.0,
    fft_y_mode: str = "magnitude",
    assume_10khz_when_no_time: bool = False,
) -> Dict[str, dict]:
    """Run strict 10 kHz DCBus FFT/PSD plus 10-second record stability.

    This remains the two-channel convenience path.  The generic
    cdcu_scope_fft.py utility supports one to four arbitrary oscilloscope
    channels with the same spectral and stability calculations.
    """
    data = validate_dcbus_capture(
        df, assume_10khz_when_no_time=assume_10khz_when_no_time
    )
    channels = [
        ScopeChannel("dcbus_v_V", "DCBus Input Voltage", "V", vbus_ref),
        ScopeChannel("dcbus_i_A", "DCBus Input Current", "A", ibus_ref),
    ]
    results = analyze_scope_dataframe(
        data,
        outdir=outdir,
        channels=channels,
        time_column="time_s",
        sample_rate_hz=DCBUS_FS_HZ,
        expected_samples=DCBUS_N_SAMPLES,
        load_desc=load_desc,
        acq_timestamp=acq_timestamp,
        logo_path=logo_path,
        sig_threshold_ppm=sig_threshold_ppm,
        fft_y_mode=fft_y_mode,
        source_csv=f"{prefix} hardware-timed capture",
    )
    return results

def analyze_dcbus_csv(csv_path: str, **kwargs) -> Dict[str, dict]:
    """Load a DCBus hardware capture CSV and analyze both input channels."""
    path = Path(csv_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"DCBus capture CSV not found: {path}")
    df = pd.read_csv(path)
    outdir = kwargs.pop("outdir", None) or str(path.parent / f"{path.stem}_dcbus_fft_psd")
    return analyze_dcbus_dataframe(df, outdir=outdir, **kwargs)


def acquire_dcbus_native_10khz(*_args, **_kwargs) -> pd.DataFrame:
    """Reserved native-acquisition hook.

    The documented CDCU Ethernet/PMM interface does not expose 10 kHz DCBus
    voltage/current buffers.  This function intentionally fails rather than
    interpolating sequential MRP/MGPC reads into a fictitious PMM-equivalent
    record.  It is the integration point for a future CAEN vendor command,
    embedded-scope DMA channel, or external synchronized DAQ backend.
    """
    raise NotImplementedError(
        "No documented CDCU native interface exposes MRP/MGPC as a synchronized "
        "100,001-sample, 10 kHz buffer. Use a hardware-timed DCBus capture CSV "
        "or add a validated vendor/DAQ acquisition backend."
    )


def _main() -> int:
    p = argparse.ArgumentParser(description="10 kHz DCBus input voltage/current FFT/PSD analyzer")
    p.add_argument("--csv", required=True, help="Hardware-timed DCBus CSV (MRP/MGPC or canonical names)")
    p.add_argument("--outdir", default=None)
    p.add_argument("--vbus-ref", type=float, default=None)
    p.add_argument("--ibus-ref", type=float, default=None)
    p.add_argument("--load-desc", default=None)
    p.add_argument("--fft-y", choices=["magnitude", "percent", "ppm"], default="magnitude")
    p.add_argument("--assume-10khz", action="store_true",
                   help="Create time_s only when the source hardware is known to be exactly 10 kHz")
    args = p.parse_args()
    results = analyze_dcbus_csv(
        args.csv,
        outdir=args.outdir,
        vbus_ref=args.vbus_ref,
        ibus_ref=args.ibus_ref,
        load_desc=args.load_desc,
        fft_y_mode=args.fft_y,
        assume_10khz_when_no_time=args.assume_10khz,
    )
    print(f"DCBus spectral analysis complete: {', '.join(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
