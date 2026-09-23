#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""
cdcu_ripple_psd.py   (renamed from ripple_psd.py)

TDK-PS / ripple_exec style plots, fully reconciled with ripple_exec.py.

Features added vs original ripple_psd.py (all from ripple_exec.py):
  1. Top-N peak annotations with arrowheads  (FFT callouts: top-3 components below 1 kHz)
  2. semilogx FFT display                    (ripple_exec: log-x / log-y via semilogx+yscale)
  3. channel_scale factor                    (ripple_exec: V_TO_I_SCALE = 500 A/V shunt)
  4. Generation timestamp on every figure    (ripple_exec: "Plot generated on ...")
  5. Data acquisition timestamp header       (ripple_exec: "Data record time: ...")
  6. Oscilloscope / scope image inset        (ripple_exec: upper-right PNG embed)
  7. Load description at lower position      (ripple_exec: ax3.text(0.22, 0.10, ...))
  8. Composite 8.5x11 single-page layout    (ripple_exec: GridSpec, title, logo footer)
  9. Band shading on all plots               (from previous CDCU work)
 10. Logo footer inset on all individual PNGs

Callouts (individual PNGs):
  FFT            : top-3 components below 1 kHz with arrowheads and ppm labels
  PSD            : single MAX peak with arrowhead
  Integrated Power: text annotation only, no callouts

Auto x-axis scaling:
  Uses Welch PSD to detect the meaningful frequency span automatically.

Band integration:
  Bands imported from cdcu_ripple_bands.BAND_STR — one definition for the
  whole CDCU tool-chain.
"""

from __future__ import annotations

import os
import math
import textwrap
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from scipy.signal import welch, get_window
from scipy.integrate import trapezoid

# Shared band definitions — change in one place, propagates everywhere
from cdcu_ripple_bands import BAND_STR as DEFAULT_BAND_STR

DEFAULT_XMIN_HZ = 1e-2
DEFAULT_XMAX_HZ = 1e4
STANDARD_PLOT_FMAX_HZ = 1200.0  # keep the 1 kHz standard band visible when Nyquist permits

# Use SciPy's supported trapezoidal integrator.  This avoids the NumPy
# np.trapz deprecation path while keeping the numerical operation explicit.
_psd_integral = trapezoid


# ---------------------------------------------------------------------------
# Band parsing
# ---------------------------------------------------------------------------

def parse_bands(bands: str) -> List[Tuple[float, float, str]]:
    """Parse compact band string '1-10:1-10 Hz,60-120:60-120 Hz,...'"""
    def parse_num(s: str) -> float:
        # Capture s here; the next step uses this intermediate result directly.
        s = s.strip().lower()
        # Capture mult here; the next step uses this intermediate result directly.
        mult = 1.0
        # Take this branch only when the stated operating condition is true.
        if s.endswith("k"):
            # Capture mult here; the next step uses this intermediate result directly.
            mult = 1e3
            # Capture s here; the next step uses this intermediate result directly.
            s = s[:-1]
        # Take this branch only when the stated operating condition is true.
        elif s.endswith("m"):
            # Capture mult here; the next step uses this intermediate result directly.
            mult = 1e6
            # Capture s here; the next step uses this intermediate result directly.
            s = s[:-1]
        # Hand the finished value back to the caller.
        return float(s) * mult

    # Carry out this step before advancing to the next part of the function.
    out: List[Tuple[float, float, str]] = []
    # Walk the collection in order so every item receives the same treatment.
    for part in bands.split(","):
        # Capture part here; the next step uses this intermediate result directly.
        part = part.strip()
        # Take this branch only when the stated operating condition is true.
        if not part:
            # Skip this item and continue with the next valid candidate.
            continue
        # Carry out this step before advancing to the next part of the function.
        rng, name = part.split(":")
        # Carry out this step before advancing to the next part of the function.
        lo, hi = rng.split("-")
        # Add this observation to the ordered history so the sequence is preserved.
        out.append((parse_num(lo), parse_num(hi), name.strip()))
    # Hand the finished value back to the caller.
    return out


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def ppm(x_rms: float, ref: Optional[float]) -> Optional[float]:
    """Return x_rms / |ref| * 1e6, or None if ref is None/zero."""
    # Take this branch only when the stated operating condition is true.
    if ref is None or ref == 0:
        # Hand the finished value back to the caller.
        return None
    # Hand the finished value back to the caller.
    return (x_rms / abs(ref)) * 1e6


def sampling_uniformity(t: np.ndarray) -> Dict[str, float]:
    """Quantify timing uniformity for FFT/PSD suitability.

    Returns mean/median sample interval, coefficient of variation (CV), and the
    maximum normalized interval error. PMM data should be essentially uniform;
    network-polled data may require resampling before an FFT is meaningful.
    """
    t = np.asarray(t, dtype=float)
    dt = np.diff(t)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if len(dt) < 2:
        return {"dt_mean_s": math.nan, "dt_median_s": math.nan, "dt_cv": math.nan,
                "dt_max_error_fraction": math.nan}
    mean_dt = float(np.mean(dt))
    median_dt = float(np.median(dt))
    std_dt = float(np.std(dt))
    max_error = float(np.max(np.abs(dt - median_dt)) / median_dt) if median_dt > 0 else math.nan
    return {
        "dt_mean_s": mean_dt,
        "dt_median_s": median_dt,
        "dt_cv": std_dt / mean_dt if mean_dt > 0 else math.nan,
        "dt_max_error_fraction": max_error,
    }


def load_trace_from_df(
    df: pd.DataFrame,
    time_col: str,
    value_col: str,
    channel_scale: float = 1.0,
    *,
    resample_if_irregular: bool = False,
    timing_cv_limit: float = 1.0e-4,
) -> Tuple[np.ndarray, np.ndarray, float, float, Dict[str, object]]:
    """Load one trace and enforce the uniform-sampling requirement of FFT/Welch.

    A conventional FFT assumes samples occur on a uniform time grid.  The CDCU
    toolkit now restricts FFT/PSD to hardware-timed PMM data, so resampling is
    disabled by default.  The timing metrics are retained as an integrity check
    for imported or edited PMM files.  A PMM record that exceeds the allowed
    timing variation should be investigated rather than silently converted from
    live polling into a spectrum.
    """
    t = df[time_col].to_numpy(dtype=float)
    x = df[value_col].to_numpy(dtype=float) * channel_scale
    good = np.isfinite(t) & np.isfinite(x)
    t, x = t[good], x[good]
    if len(t) < 2:
        raise ValueError("At least two finite time/value samples are required.")
    order = np.argsort(t)
    t, x = t[order], x[order]
    # Remove duplicate timestamps because interpolation requires a strictly increasing axis.
    unique = np.concatenate(([True], np.diff(t) > 0))
    t, x = t[unique], x[unique]
    info: Dict[str, object] = dict(sampling_uniformity(t))
    dt = float(info["dt_median_s"])
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError("Unable to determine a valid sample interval from the time axis.")
    cv = float(info["dt_cv"]) if np.isfinite(info["dt_cv"]) else math.inf
    resampled = False
    if resample_if_irregular and cv > timing_cv_limit:
        t_uniform = np.arange(t[0], t[-1] + 0.5 * dt, dt, dtype=float)
        x = np.interp(t_uniform, t, x)
        t = t_uniform
        resampled = True
    fs = 1.0 / dt
    x_dc = float(np.mean(x))
    info["timing_cv_limit"] = float(timing_cv_limit)
    info["resampled"] = resampled
    info["sample_count_after_preparation"] = int(len(x))
    return t, x, fs, x_dc, info


def recommended_welch_nperseg(sample_count: int, target: int = 16384) -> int:
    """Choose a practical Welch segment length without exceeding the record.

    PMM captures at 10 kHz use a 16,384-sample Welch segment whenever the record
    is long enough.  At 10 kHz this gives approximately 0.61035 Hz/bin, which
    improves resolution of the 1-10 Hz band while retaining multiple Welch averages.
    """
    n = int(sample_count)
    if n < 64:
        return max(8, n)
    candidates = (16384, 8192, 4096, 2048, 1024, 512, 256, 128, 64)
    ceiling = min(int(target), n)
    for candidate in candidates:
        if candidate <= ceiling:
            return candidate
    return max(64, ceiling)

def single_sided_fft_rms(
    x: np.ndarray, fs: float, window: str = "hann"
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute a coherent-gain-corrected single-sided RMS line spectrum.

    Interior positive-frequency bins are doubled to account for the omitted
    negative-frequency half of a real-valued FFT. DC and the Nyquist bin are not
    doubled. Interior sinusoidal peak amplitudes are converted to RMS by /sqrt(2).
    """
    x = np.asarray(x, dtype=float)
    N = len(x)
    if N < 2:
        raise ValueError("FFT requires at least two samples.")
    w = get_window(window, N, fftbins=True)
    xw = (x - np.mean(x)) * w
    X = np.fft.rfft(xw)
    freqs = np.fft.rfftfreq(N, d=1.0 / fs)
    wsum = float(np.sum(w))
    if wsum == 0.0:
        raise ValueError("FFT window coherent gain is zero.")

    # Two-sided coherent-gain-corrected amplitude before single-sided folding.
    A = np.abs(X) / wsum
    A_rms = A.copy()
    if N % 2 == 0:
        interior = slice(1, -1)  # exclude DC and Nyquist
    else:
        interior = slice(1, None)  # exclude DC; no Nyquist bin for odd N
    A_rms[interior] = (2.0 * A[interior]) / np.sqrt(2.0)
    # DC and Nyquist (when present) are their own real-valued components; RMS=amplitude.
    return freqs, A_rms

def welch_psd(
    x: np.ndarray,
    fs: float,
    nperseg: int = 16384,
    overlap: float = 0.5,
    window: str = "hann",
) -> Tuple[np.ndarray, np.ndarray]:
    """Welch PSD estimate with safe overlap clamping."""
    # Capture x here; the next step uses this intermediate result directly.
    x = np.asarray(x, dtype=float)
    # Capture x here; the next step uses this intermediate result directly.
    x = x - np.mean(x)
    # Capture nper here; the next step uses this intermediate result directly.
    nper = min(nperseg, len(x))
    # Capture noverlap here; the next step uses this intermediate result directly.
    noverlap = int(nper * overlap)
    # Take this branch only when the stated operating condition is true.
    if noverlap >= nper:
        # Capture noverlap here; the next step uses this intermediate result directly.
        noverlap = max(0, nper - 1)
    # Carry out this step before advancing to the next part of the function.
    f, Pxx = welch(x, fs=fs, window=window, nperseg=nper, noverlap=noverlap)
    # Hand the finished value back to the caller.
    return f, Pxx


def integrate_psd_rms(
    Pxx: np.ndarray, f: np.ndarray, lo: float, hi: float
) -> float:
    """Integrate PSD over [lo, hi] with interpolated band edges.

    Interpolating the PSD at the requested band boundaries reduces sensitivity
    to whether a coarse Welch bin happens to land just inside or outside a band.
    """
    f = np.asarray(f, dtype=float)
    Pxx = np.asarray(Pxx, dtype=float)
    if len(f) < 2 or hi <= lo:
        return 0.0
    lo_eff = max(float(lo), float(f[0]))
    hi_eff = min(float(hi), float(f[-1]))
    if hi_eff <= lo_eff:
        return 0.0
    interior = (f > lo_eff) & (f < hi_eff)
    f_band = np.concatenate(([lo_eff], f[interior], [hi_eff]))
    p_band = np.concatenate(([np.interp(lo_eff, f, Pxx)], Pxx[interior],
                             [np.interp(hi_eff, f, Pxx)]))
    power = float(_psd_integral(p_band, f_band))
    return float(np.sqrt(max(power, 0.0)))

def cumulative_integrated_power(
    Pxx: np.ndarray, f: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Cumulative integral of PSD -- equivalent to ripple_exec's np.cumsum(Ipower)*df."""
    # Capture cum here; the next step uses this intermediate result directly.
    cum = np.zeros_like(f, dtype=float)
    # Walk the collection in order so every item receives the same treatment.
    for i in range(1, len(f)):
        # Capture cum[i] here; the next step uses this intermediate result directly.
        cum[i] = cum[i - 1] + 0.5 * (Pxx[i] + Pxx[i - 1]) * (f[i] - f[i - 1])
    # Hand the finished value back to the caller.
    return f, cum


# ---------------------------------------------------------------------------
# Plot style helpers
# ---------------------------------------------------------------------------

def _style_axes_tdk(ax: plt.Axes) -> None:
    """Apply TDK-style major + minor grid."""
    # Carry out this step before advancing to the next part of the function.
    ax.minorticks_on()
    # Carry out this step before advancing to the next part of the function.
    ax.grid(True, which="major", linestyle="-", alpha=0.35)
    # Carry out this step before advancing to the next part of the function.
    ax.grid(True, which="minor", linestyle=":", alpha=0.35)


def _auto_freq_limits_from_psd(
    f: np.ndarray,
    Pxx: np.ndarray,
    fs: float,
    user_xmin: float,
    user_xmax: float,
    floor_ratio: float = 1e-8,
    pad_ratio: float = 1.15,
) -> Tuple[float, float]:
    """Detect meaningful x-axis span from PSD content."""
    # Capture f here; the next step uses this intermediate result directly.
    f = np.asarray(f, dtype=float)
    # Capture Pxx here; the next step uses this intermediate result directly.
    Pxx = np.asarray(Pxx, dtype=float)

    # Capture m here; the next step uses this intermediate result directly.
    m = (f > 0) & np.isfinite(Pxx) & (Pxx >= 0)
    # Carry out this step before advancing to the next part of the function.
    f2, p2 = f[m], Pxx[m]
    # Make sure enough samples are available before running the calculation.
    if len(f2) < 4:
        # Hand the finished value back to the caller.
        return user_xmin, min(user_xmax, 0.5 * fs)

    # Capture pmax here; the next step uses this intermediate result directly.
    pmax = float(np.max(p2))
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if not np.isfinite(pmax) or pmax <= 0:
        # Hand the finished value back to the caller.
        return user_xmin, min(user_xmax, 0.5 * fs)

    # Capture floor here; the next step uses this intermediate result directly.
    floor = max(pmax * floor_ratio, 1e-30)
    # Capture above here; the next step uses this intermediate result directly.
    above = p2 > floor
    # Take this branch only when the stated operating condition is true.
    if not np.any(above):
        # Hand the finished value back to the caller.
        return user_xmin, min(user_xmax, 0.5 * fs)

    # Capture xmin here; the next step uses this intermediate result directly.
    xmin = float(f2[np.argmax(above)])
    # Capture xmax here; the next step uses this intermediate result directly.
    xmax = float(f2[len(above) - 1 - np.argmax(above[::-1])]) * pad_ratio

    # Capture nyq here; the next step uses this intermediate result directly.
    nyq = 0.5 * fs
    # Capture xmin here; the next step uses this intermediate result directly.
    xmin = max(user_xmin, xmin)
    # Capture xmax here; the next step uses this intermediate result directly.
    xmax = min(user_xmax, nyq, xmax)

    # Keep the standard spectral display wide enough to include 1 kHz whenever
    # the acquisition bandwidth permits it.  Revision 18 defines 720-1200 Hz
    # as the standard 1 kHz band, so 1 kHz is inside the band rather than on
    # its boundary.
    standard_xmax = min(user_xmax, nyq, STANDARD_PLOT_FMAX_HZ)
    xmax = max(xmax, standard_xmax)

    # Take this branch only when the stated operating condition is true.
    if xmax <= xmin * 1.05:
        # Capture xmax here; the next step uses this intermediate result directly.
        xmax = min(user_xmax, nyq, xmin * 10.0)

    # Hand the finished value back to the caller.
    return xmin, xmax


def _max_point_in_band(
    x: np.ndarray, y: np.ndarray, xmin: float, xmax: float
) -> Optional[Tuple[float, float, int]]:
    """Return (x, y, idx) of the global maximum within [xmin, xmax], x > 0."""
    # Capture x here; the next step uses this intermediate result directly.
    x = np.asarray(x, dtype=float)
    # Capture y here; the next step uses this intermediate result directly.
    y = np.asarray(y, dtype=float)
    # Capture m here; the next step uses this intermediate result directly.
    m = (x >= xmin) & (x <= xmax) & (x > 0) & np.isfinite(y)
    # Take this branch only when the stated operating condition is true.
    if not np.any(m):
        # Hand the finished value back to the caller.
        return None
    # Capture idxs here; the next step uses this intermediate result directly.
    idxs = np.where(m)[0]
    # Capture j here; the next step uses this intermediate result directly.
    j = idxs[np.argmax(y[m])]
    # Hand the finished value back to the caller.
    return float(x[j]), float(y[j]), int(j)


def _top_n_peaks_in_band(
    x: np.ndarray,
    y: np.ndarray,
    xmin: float,
    xmax: float,
    n: int = 2,
) -> List[Tuple[float, float, int]]:
    """
    Return up to *n* (x, y, idx) tuples of the highest y values within
    [xmin, xmax], sorted descending.  Matches ripple_exec.py:
        peak_indices = np.argsort(Ipower[StartF:FinalF])[-2:] + StartF
    """
    # Capture x here; the next step uses this intermediate result directly.
    x = np.asarray(x, dtype=float)
    # Capture y here; the next step uses this intermediate result directly.
    y = np.asarray(y, dtype=float)
    # Capture m here; the next step uses this intermediate result directly.
    m = (x >= xmin) & (x <= xmax) & (x > 0) & np.isfinite(y)
    # Take this branch only when the stated operating condition is true.
    if not np.any(m):
        # Hand the finished value back to the caller.
        return []
    # Capture idxs here; the next step uses this intermediate result directly.
    idxs = np.where(m)[0]
    # Capture top here; the next step uses this intermediate result directly.
    top = idxs[np.argsort(y[m])[::-1][:n]]
    # Hand the finished value back to the caller.
    return [(float(x[j]), float(y[j]), int(j)) for j in top]


def _annotate_bands(
    ax: plt.Axes,
    bands: List[Tuple[float, float, str]],
    xmin: float,
    xmax: float,
    alpha: float = 0.10,
) -> None:
    """Shade each analysis band with a distinct colour and legend entry."""
    # Capture colors here; the next step uses this intermediate result directly.
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
    # Walk the collection in order so every item receives the same treatment.
    for i, (lo, hi, label) in enumerate(bands):
        # Capture lo_c here; the next step uses this intermediate result directly.
        lo_c = max(lo, xmin)
        # Capture hi_c here; the next step uses this intermediate result directly.
        hi_c = min(hi, xmax)
        # Take this branch only when the stated operating condition is true.
        if lo_c >= hi_c:
            # Skip this item and continue with the next valid candidate.
            continue
        # Carry out this step before advancing to the next part of the function.
        ax.axvspan(lo_c, hi_c, alpha=alpha, color=colors[i % len(colors)],
                   label=f"Band: {label}")


def _add_figure_footer(
    fig: plt.Figure,
    logo_path: Optional[str],
    acq_timestamp: Optional[str] = None,
) -> None:
    """
    Add generation timestamp (lower-left) and optional logo inset (lower-right).
    Matches ripple_exec.py footer:
        fig.text(0.01, 0.015, f"Plot generated on {datetime...}")
        ax_logo = fig.add_axes([0.76, 0.01, 0.22, 0.07])
    acq_timestamp: data acquisition time shown above the generation stamp.
    """
    # Capture gen_str here; the next step uses this intermediate result directly.
    gen_str = f"Plot generated on {datetime.now().strftime('%Y-%m-%d at %H:%M:%S')}"
    # Take this branch only when the stated operating condition is true.
    if acq_timestamp:
        # Capture gen_str here; the next step uses this intermediate result directly.
        gen_str = f"{acq_timestamp}\n{gen_str}"
    # Carry out this step before advancing to the next part of the function.
    fig.text(0.01, 0.01, gen_str, fontsize=7, ha="left", va="bottom", color="dimgray")

    # Take this branch only when the stated operating condition is true.
    if logo_path and os.path.isfile(logo_path):
        # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
        try:
            # Import this dependency locally because it is only needed on this execution path.
            from PIL import Image as _PILImage
            # Resolve the local APS/Argonne branding image used by the report output.
            logo = _PILImage.open(logo_path)
            # Capture ax_logo here; the next step uses this intermediate result directly.
            ax_logo = fig.add_axes([0.70, 0.008, 0.29, 0.065])
            # Carry out this step before advancing to the next part of the function.
            ax_logo.imshow(logo)
            # Carry out this step before advancing to the next part of the function.
            ax_logo.axis("off")
        except Exception:
            # No action is required in this branch; keep the control flow explicit.
            pass  # logo is decorative -- never crash on failure


# ---------------------------------------------------------------------------
# Individual plot functions
# ---------------------------------------------------------------------------

def _fft_display_scale(
    A_rms: np.ndarray,
    ppm_ref: Optional[float],
    quantity_unit: str,
    mode: str,
) -> Tuple[np.ndarray, str]:
    """Return FFT magnitude values in the operator-selected engineering display scale."""
    # Normalize the requested mode once so every branch interprets the same input.
    selected = (mode or "magnitude").strip().lower()
    # Work on a numeric copy so plot scaling never changes the source FFT data.
    values = np.asarray(A_rms, dtype=float)
    # Express the spectrum directly in ppm when the operator asks for ppm.
    if selected == "ppm":
        # A valid nonzero reference is required before an absolute magnitude can become ppm.
        if ppm_ref is None or not np.isfinite(ppm_ref) or ppm_ref == 0:
            # Fail clearly instead of drawing a ppm axis from an undefined reference.
            raise ValueError("FFT ppm display requires a finite, nonzero ppm reference.")
        # Convert each RMS spectral component to parts per million of the engineering reference.
        return values / abs(ppm_ref) * 1e6, "RMS Amplitude (ppm)"
    # Express the spectrum directly in percent when the operator asks for percent.
    if selected == "percent":
        # A valid nonzero reference is required before an absolute magnitude can become percent.
        if ppm_ref is None or not np.isfinite(ppm_ref) or ppm_ref == 0:
            # Fail clearly instead of drawing a percent axis from an undefined reference.
            raise ValueError("FFT percent display requires a finite, nonzero reference.")
        # Convert each RMS spectral component to percent of the engineering reference.
        return values / abs(ppm_ref) * 100.0, "RMS Amplitude (%)"
    # Reject unknown modes before they reach the plotting path.
    if selected != "magnitude":
        # Name the accepted choices so a command-line typo is easy to correct.
        raise ValueError("fft_y_mode must be 'magnitude', 'percent', or 'ppm'.")
    # Use milliamps for current spectra below 1 A so the plotted numbers remain easy to read.
    if quantity_unit == "A" and np.nanmax(values) < 1.0:
        # Scale amperes to milliamps without changing the underlying FFT result object.
        return values * 1000.0, "RMS Amplitude (mA)"
    # Use millivolts for voltage spectra below 1 V for the same readability reason.
    if quantity_unit == "V" and np.nanmax(values) < 1.0:
        # Scale volts to millivolts without changing the underlying FFT result object.
        return values * 1000.0, "RMS Amplitude (mV)"
    # Leave larger physical values in their native engineering unit.
    return values, f"RMS Amplitude ({quantity_unit})"


def _dominant_band_summary(
    band_rms: Optional[List[Tuple[str, float, float, float, Optional[float]]]],
) -> Optional[Tuple[str, float, float, float, Optional[float]]]:
    """Return the frequency band with the largest integrated RMS contribution."""
    # A missing band table means there is no band comparison to summarize.
    if not band_rms:
        # Return None so the report can omit the dominant-band line cleanly.
        return None
    # Ignore malformed or non-finite RMS entries before ranking the bands.
    usable = [row for row in band_rms if len(row) >= 5 and np.isfinite(row[3])]
    # Stop here if no band contains a usable integrated RMS value.
    if not usable:
        # Return None rather than inventing a dominant band from invalid data.
        return None
    # The largest RMS contribution identifies the dominant integrated band.
    return max(usable, key=lambda row: row[3])


def plot_fft_tdk(
    freqs: np.ndarray,
    A_rms: np.ndarray,
    out_png: str,
    xmin: float,
    xmax: float,
    title: str,
    dc_value: float,
    total_ripple_rms: float,
    unit_rms_label: str,
    ppm_ref: Optional[float],
    ppm_ref_label: str = "engineering reference",
    bands: Optional[List[Tuple[float, float, str]]] = None,
    band_rms: Optional[List[Tuple[str, float, float, float, Optional[float]]]] = None,
    n_peaks: int = 3,
    logo_path: Optional[str] = None,
    load_desc: Optional[str] = None,
    acq_timestamp: Optional[str] = None,
    log_y: bool = False,
    fft_y_mode: str = "magnitude",
) -> None:
    """Draw the primary FFT as a linear, filled spectrum with an engineering summary box."""
    # Create a wide figure because the filled spectrum is intended to be the first-look diagnostic view.
    fig, ax = plt.subplots(figsize=(10, 5.5))
    # Keep only positive-frequency bins inside the requested display range.
    mask = (freqs >= xmin) & (freqs <= xmax) & (freqs >= 0)
    # Convert the RMS spectrum to the operator-selected engineering display scale.
    display_values, y_label = _fft_display_scale(A_rms, ppm_ref, unit_rms_label.strip("()rms"), fft_y_mode)
    # Pull the selected frequencies into a compact array for plotting and peak extraction.
    plot_freqs = freqs[mask]
    # Pull the matching magnitude values so both arrays remain index aligned.
    plot_values = display_values[mask]
    # Draw the FFT trace itself before filling the area below it.
    ax.plot(plot_freqs, plot_values, linewidth=1.2, color="steelblue")
    # Fill from zero to the FFT curve to match the preferred spectrum-summary visual style.
    ax.fill_between(plot_freqs, 0.0, plot_values, alpha=0.80, color="steelblue")
    # Use a linear frequency axis so harmonic spacing is immediately visible by eye.
    ax.set_xlim(max(0.0, xmin), xmax)
    # Start the magnitude axis at zero because this is an amplitude summary, not a logarithmic floor plot.
    ax.set_ylim(bottom=0.0)
    # Label the frequency axis in hertz for direct engineering interpretation.
    ax.set_xlabel("Frequency (Hz)")
    # Label the magnitude axis in the selected engineering scale.
    ax.set_ylabel(y_label)
    # Use the short title requested for a first-look spectral diagnostic.
    ax.set_title("FFT Analysis" if not title else f"FFT Analysis - {title}", fontweight="bold")
    # Keep the grid light enough to support reading values without hiding narrow spectral components.
    ax.grid(True, which="major", linestyle="-", alpha=0.22)
    # Retain minor ticks but avoid a dense minor grid that competes with the filled trace.
    ax.minorticks_on()

    # Find the strongest FFT components in the same frequency interval shown on the graph.
    peaks = _top_n_peaks_in_band(freqs, A_rms, max(xmin, 0.0), xmax, n=max(1, n_peaks))
    # Track formatted peak metadata so the summary box and the on-plot callouts stay consistent.
    peak_records: List[Dict[str, float | str]] = []
    # Build compact peak text for the summary box.
    peak_lines: List[str] = []
    # Walk the dominant components from strongest to weaker in the order returned by the peak finder.
    for peak_rank, (fpk, apk, _idx) in enumerate(peaks, start=1):
        # Convert each peak through the same display-scale helper used by the plotted spectrum.
        peak_display, _unused_label = _fft_display_scale(np.asarray([apk]), ppm_ref, unit_rms_label.strip("()rms"), fft_y_mode)
        # Capture the plotted magnitude in the currently selected engineering units.
        peak_value = float(peak_display[0])
        # Convert the same component to ppm when a valid reference is available.
        peak_ppm = ppm(apk, ppm_ref)
        # Record one concise line for the summary box.
        peak_line = f"{peak_rank}) {fpk:.2f} Hz: {peak_value:.3g}"
        if peak_ppm is not None:
            peak_line += f" | {peak_ppm:.3f} ppm"
        peak_lines.append(peak_line)
        # Store the full peak record so the annotation pass can reuse the same values.
        peak_records.append({
            "rank": peak_rank,
            "freq_hz": float(fpk),
            "display_value": peak_value,
            "display_y": peak_value,
            "ppm": None if peak_ppm is None else float(peak_ppm),
        })

    # Express total ripple in both percent and ppm whenever a reference is available.
    ppm_total = ppm(total_ripple_rms, ppm_ref)
    # Convert the same relative ripple quantity to percent for side-by-side reporting.
    pct_total = None if ppm_total is None else ppm_total / 10000.0
    # Start the summary with the DC operating point because every ppm value depends on its reference context.
    summary_lines = [f"DC reference: {dc_value:.6g} {unit_rms_label.strip('()rms')}"]
    # Add the time-domain RMS ripple in its native physical unit.
    summary_lines.append(f"Total ripple RMS: {total_ripple_rms:.6g} {unit_rms_label.strip('()rms')}")
    # Add relative ripple in both percent and ppm when the reference is valid.
    if ppm_total is not None and pct_total is not None:
        # Report both units because percent is intuitive while ppm is the normal precision-power metric.
        summary_lines.append(f"Ripple: {pct_total:.6g}% | {ppm_total:.3f} ppm ({ppm_ref_label})")
    # Identify the dominant integrated frequency band when band calculations are available.
    dominant_band = _dominant_band_summary(band_rms)
    # Add the band name and RMS/ppm contribution to the first-look summary.
    if dominant_band is not None:
        # Unpack the stored band result in the same order produced by analyze_series_for_reports.
        name, lo, hi, rms_value, rms_ppm = dominant_band
        # Start with the band edges and physical RMS contribution.
        band_line = f"Dominant band: {name} ({lo:g}-{hi:g} Hz), {rms_value:.4g} {unit_rms_label.strip('()rms')}"
        # Add ppm when the band has a valid engineering reference.
        if rms_ppm is not None:
            # Preserve both the physical value and ppm because they answer different troubleshooting questions.
            band_line += f" | {rms_ppm:.3f} ppm"
        # Append the completed band line to the report box.
        summary_lines.append(band_line)
    # Add the strongest individual spectral components below the aggregate metrics.
    if peak_lines:
        # Label the following lines so an engineer can distinguish discrete peaks from integrated band results.
        summary_lines.append("Dominant Components:")
        # Keep one peak per line so the box stays readable when ppm values are included.
        summary_lines.extend([f"  {line}" for line in peak_lines])
    # Keep the load description tied to the dominant-component summary so it is easy to reference.
    if load_desc:
        # Add an explicit label, then wrap the load text so long magnet descriptions do not force an oversized box.
        summary_lines.append("Load Description:")
        summary_lines.extend([f"  {line}" for line in textwrap.wrap(load_desc, width=52)])

    # Draw a compact summary box in the open upper-right area of the plot.
    ax.text(
        0.985,
        0.97,
        "\n".join(summary_lines),
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="0.75", alpha=0.92),
    )
    # Select the three strongest FFT components strictly below 1 kHz for callouts.
    # This selection is intentionally independent of the summary-box ranking so the
    # arrows always emphasize the sub-1-kHz components requested for troubleshooting.
    callout_fmax_hz = min(float(xmax), float(np.nextafter(1000.0, -np.inf)))
    callout_peaks = _top_n_peaks_in_band(
        freqs,
        A_rms,
        max(float(xmin), 0.0),
        callout_fmax_hz,
        n=3,
    )
    callout_records: List[Dict[str, float | str]] = []
    for callout_rank, (fpk, apk, _idx) in enumerate(callout_peaks, start=1):
        peak_display, _unused_label = _fft_display_scale(
            np.asarray([apk]),
            ppm_ref,
            unit_rms_label.strip("()rms"),
            fft_y_mode,
        )
        peak_value = float(peak_display[0])
        peak_ppm = ppm(apk, ppm_ref)
        callout_records.append({
            "rank": callout_rank,
            "freq_hz": float(fpk),
            "display_value": peak_value,
            "display_y": peak_value,
            "ppm": None if peak_ppm is None else float(peak_ppm),
        })

    # Keep all three callout boxes inside the plot and vertically separated.
    callout_positions = [(0.03, 0.93), (0.03, 0.77), (0.03, 0.61)]
    # Use a short engineering unit string so the callout boxes stay compact.
    if fft_y_mode == "magnitude":
        # Pull the display unit from the axis label so the callout matches any auto-scaled mA / mV units.
        if "(" in y_label and ")" in y_label:
            callout_unit = y_label.split("(", 1)[1].split(")", 1)[0]
        else:
            callout_unit = unit_rms_label.strip("()rms")
    elif fft_y_mode == "percent":
        # Preserve the selected percent engineering mode explicitly.
        callout_unit = "%"
    else:
        # Preserve the selected ppm engineering mode explicitly.
        callout_unit = "ppm"
    for peak_record, (xf, yf) in zip(callout_records, callout_positions):
        # Build a compact multi-line label for each dominant component.
        callout_lines = [
            f"Peak {int(peak_record['rank'])}",
            f"{peak_record['freq_hz']:.2f} Hz",
            f"{peak_record['display_value']:.3g} {callout_unit}",
        ]
        if peak_record['ppm'] is not None and fft_y_mode != "ppm":
            callout_lines.append(f"{peak_record['ppm']:.3f} ppm")
        # Draw the callout inside the axes and point it back to the actual spectral peak.
        ax.annotate(
            "\n".join(callout_lines),
            xy=(peak_record['freq_hz'], peak_record['display_y']),
            xycoords='data',
            xytext=(xf, yf),
            textcoords='axes fraction',
            ha='left',
            va='top',
            fontsize=7,
            bbox=dict(boxstyle='round,pad=0.30', facecolor='white', edgecolor='0.65', alpha=0.95),
            arrowprops=dict(arrowstyle='->', color='0.25', lw=0.9, shrinkA=4, shrinkB=4),
            annotation_clip=False,
        )
    # Leave footer space for the acquisition timestamp and APS/Argonne branding.
    fig.tight_layout(rect=[0, 0.07, 1, 1])
    # Add the existing report footer so the new graphic remains consistent with the rest of the toolkit.
    _add_figure_footer(fig, logo_path, acq_timestamp)
    # Save the primary FFT summary at report quality.
    fig.savefig(out_png, dpi=180, bbox_inches="tight")
    # Release the matplotlib figure so repeated PMM analysis does not accumulate GUI resources.
    plt.close(fig)


# Backward-compat alias for callers using the old name
plot_fft_tdk_single_callout = plot_fft_tdk


def plot_psd_tdk(
    f: np.ndarray,
    Pxx: np.ndarray,
    out_png: str,
    xmin: float,
    xmax: float,
    title: str,
    unit2_per_hz_label: str,
    bands: Optional[List[Tuple[float, float, str]]] = None,
    logo_path: Optional[str] = None,
    acq_timestamp: Optional[str] = None,
) -> None:
    """PSD plot (log-log) with single MAX arrowhead callout and optional band shading."""
    # Carry out this step before advancing to the next part of the function.
    fig, ax = plt.subplots(figsize=(10, 5))

    # Capture m here; the next step uses this intermediate result directly.
    m = (f >= xmin) & (f <= xmax) & (f > 0)
    # Carry out this step before advancing to the next part of the function.
    ax.loglog(f[m], np.maximum(Pxx[m], 1e-30), color="steelblue")

    # Take this branch only when the stated operating condition is true.
    if bands:
        # Carry out this step before advancing to the next part of the function.
        _annotate_bands(ax, bands, xmin, xmax)
        # Carry out this step before advancing to the next part of the function.
        ax.legend(loc="upper right", fontsize=8)

    # Carry out this step before advancing to the next part of the function.
    ax.set_xlim(xmin, xmax)
    # Carry out this step before advancing to the next part of the function.
    ax.set_xlabel("Frequency (Hz)")
    # Carry out this step before advancing to the next part of the function.
    ax.set_ylabel(unit2_per_hz_label)
    # Carry out this step before advancing to the next part of the function.
    ax.set_title(title, loc="left", pad=-5)
    # Carry out this step before advancing to the next part of the function.
    _style_axes_tdk(ax)

    # Capture peak here; the next step uses this intermediate result directly.
    peak = _max_point_in_band(f, Pxx, xmin, xmax)
    # Take this branch only when the stated operating condition is true.
    if peak is not None:
        # Carry out this step before advancing to the next part of the function.
        fpk, ppk, _ = peak
        # Carry out this step before advancing to the next part of the function.
        ax.annotate(
            f"MAX\n{fpk:.2f} Hz\n{ppk:.3g}",
            xy=(fpk, ppk),
            xytext=(fpk * 2.0, ppk * 2.0),
            arrowprops=dict(arrowstyle="->", color="black", lw=1.0),
            fontsize=9,
        )

    # Carry out this step before advancing to the next part of the function.
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    # Carry out this step before advancing to the next part of the function.
    _add_figure_footer(fig, logo_path, acq_timestamp)
    # Carry out this step before advancing to the next part of the function.
    fig.savefig(out_png, dpi=150)
    # Carry out this step before advancing to the next part of the function.
    plt.close(fig)


# Backward-compat alias
plot_psd_tdk_single_callout = plot_psd_tdk


def plot_integrated_power_tdk(
    f: np.ndarray,
    cum_power: np.ndarray,
    out_png: str,
    xmin: float,
    xmax: float,
    title: str,
    unit2_label: str,
    text_lines: List[str],
    bands: Optional[List[Tuple[float, float, str]]] = None,
    load_desc: Optional[str] = None,
    logo_path: Optional[str] = None,
    acq_timestamp: Optional[str] = None,
) -> None:
    """
    Cumulative integrated power plot (log-log) with text summary and optional
    load description at the lower position -- matching ripple_exec.py ax3 layout:
        ax3.text(0.02, 0.95, ...)   <- integrated metrics (upper-left)
        ax3.text(0.22, 0.10, ...)   <- load description (lower)
    """
    # Carry out this step before advancing to the next part of the function.
    fig, ax = plt.subplots(figsize=(10, 5))

    # Capture m here; the next step uses this intermediate result directly.
    m = (f >= xmin) & (f <= xmax) & (f > 0)
    # Carry out this step before advancing to the next part of the function.
    ax.loglog(f[m], np.maximum(cum_power[m], 1e-30), color="steelblue")

    # Take this branch only when the stated operating condition is true.
    if bands:
        # Carry out this step before advancing to the next part of the function.
        _annotate_bands(ax, bands, xmin, xmax)
        # Carry out this step before advancing to the next part of the function.
        ax.legend(loc="upper right", fontsize=8)

    # Carry out this step before advancing to the next part of the function.
    ax.set_xlim(xmin, xmax)
    # Carry out this step before advancing to the next part of the function.
    ax.set_xlabel("Frequency (Hz)")
    # Carry out this step before advancing to the next part of the function.
    ax.set_ylabel(unit2_label)
    # Carry out this step before advancing to the next part of the function.
    ax.set_title(title, loc="left", pad=-5)
    # Carry out this step before advancing to the next part of the function.
    _style_axes_tdk(ax)

    # Upper-left: integrated RMS and band summary
    # Carry out this step before advancing to the next part of the function.
    ax.text(
        0.02, 0.95, "\n".join(text_lines),
        transform=ax.transAxes, fontsize=8, va="top",
    )

    # Lower load description -- matches ripple_exec.py ax3.text(0.22, 0.10, ...)
    # Do not judge full-load performance until the load is high enough to make that comparison meaningful.
    if load_desc:
        # Carry out this step before advancing to the next part of the function.
        ax.text(
            0.22, 0.04, load_desc,
            transform=ax.transAxes, fontsize=7, va="bottom", color="dimgray",
        )

    # Carry out this step before advancing to the next part of the function.
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    # Carry out this step before advancing to the next part of the function.
    _add_figure_footer(fig, logo_path, acq_timestamp)
    # Carry out this step before advancing to the next part of the function.
    fig.savefig(out_png, dpi=150)
    # Carry out this step before advancing to the next part of the function.
    plt.close(fig)


# ---------------------------------------------------------------------------
# Composite single-page report figure  (from ripple_exec.py)
# ---------------------------------------------------------------------------

def plot_composite_report(
    freqs: np.ndarray,
    A_rms: np.ndarray,
    f_psd: np.ndarray,
    Pxx: np.ndarray,
    f_cum: np.ndarray,
    cum_power: np.ndarray,
    out_png: str,
    xmin: float,
    xmax: float,
    title: str,
    dc_value: float,
    total_ripple_rms: float,
    unit_rms_label: str,
    unit2_per_hz_label: str,
    unit2_label: str,
    ppm_ref: Optional[float],
    text_lines: List[str],
    ppm_ref_label: str = "engineering reference",
    bands: Optional[List[Tuple[float, float, str]]] = None,
    band_rms: Optional[List[Tuple[str, float, float, float, Optional[float]]]] = None,
    n_peaks: int = 2,
    logo_path: Optional[str] = None,
    scope_image_path: Optional[str] = None,
    load_desc: Optional[str] = None,
    acq_timestamp: Optional[str] = None,
    fft_y_mode: str = "magnitude",
) -> None:
    """
    Composite 8.5x11 single-page report figure -- matches ripple_exec.py layout:

        Title (bold)              [scope image inset -- upper right]
        acq_timestamp
        -------------------------------------------------------
        FFT amplitude  (semilogx + log y, top-N arrowhead peaks)
        -------------------------------------------------------
        PSD            (loglog, MAX arrowhead)
        -------------------------------------------------------
        Integrated Power (cumulative loglog, metrics + load desc)
        -------------------------------------------------------
        [ANL logo]     "Plot generated on ..."

    Parameters
    ----------
    scope_image_path : Path to oscilloscope capture PNG to embed upper-right
                       (ripple_exec.py: PNG_FILE inset via ax_img).
    n_peaks          : FFT peaks to annotate (default 2, matching ripple_exec).
    """
    # Capture fig here; the next step uses this intermediate result directly.
    fig = plt.figure(figsize=(8.5, 11))

    # Title -- matches ripple_exec fig.text bold blue
    # Carry out this step before advancing to the next part of the function.
    fig.text(0.08, 0.975, title, fontsize=16, fontweight="bold",
             color="steelblue", ha="left", va="top")
    # Take this branch only when the stated operating condition is true.
    if acq_timestamp:
        # Carry out this step before advancing to the next part of the function.
        fig.text(0.08, 0.955, acq_timestamp, fontsize=9, ha="left", va="top")

    # Oscilloscope image inset (upper-right) -- matches ripple_exec ax_img
    # Take this branch only when the stated operating condition is true.
    if scope_image_path and os.path.isfile(scope_image_path):
        # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
        try:
            # Import this dependency locally because it is only needed on this execution path.
            from PIL import Image as _PILImage
            # Capture scope_img here; the next step uses this intermediate result directly.
            scope_img = _PILImage.open(scope_image_path)
            # Capture ax_scope here; the next step uses this intermediate result directly.
            ax_scope = fig.add_axes([0.64, 0.74, 0.32, 0.22])
            # Carry out this step before advancing to the next part of the function.
            ax_scope.imshow(scope_img)
            # Carry out this step before advancing to the next part of the function.
            ax_scope.axis("off")
        except Exception:
            # No action is required in this branch; keep the control flow explicit.
            pass

    # Three data subplots -- matches ripple_exec GridSpec(6, 1) rows 1-3
    # Capture gs here; the next step uses this intermediate result directly.
    gs = GridSpec(3, 1, figure=fig,
                  top=0.92, bottom=0.10, hspace=0.45,
                  left=0.10, right=0.95)

    # ── Subplot 1: FFT filled-spectrum summary ───────────────────────────────
    # Create the top axis as the fast first-look spectral view used during troubleshooting.
    ax1 = fig.add_subplot(gs[0])
    # Limit the primary FFT to the positive-frequency range selected for this report.
    m = (freqs >= xmin) & (freqs <= xmax) & (freqs >= 0)
    # Convert the FFT amplitudes to the same engineering scale requested for the standalone FFT plot.
    fft_display, fft_ylabel = _fft_display_scale(A_rms, ppm_ref, unit_rms_label.strip("()rms"), fft_y_mode)
    # Draw the spectral envelope as a line so narrow components remain visible at report scale.
    ax1.plot(freqs[m], fft_display[m], color="steelblue", linewidth=0.9)
    # Fill the area under the spectrum to match the preferred graphical summary style.
    ax1.fill_between(freqs[m], 0.0, fft_display[m], color="steelblue", alpha=0.80)
    # Keep the frequency axis linear so harmonic spacing is immediately apparent.
    ax1.set_xlim(max(0.0, xmin), xmax)
    # Begin the amplitude scale at zero because the upper panel is a linear magnitude summary.
    ax1.set_ylim(bottom=0.0)
    # Label the horizontal axis in hertz.
    ax1.set_xlabel("Frequency (Hz)", fontsize=8)
    # Label the vertical axis in the selected engineering scale.
    ax1.set_ylabel(fft_ylabel, fontsize=8)
    # Keep the short title consistent with the standalone FFT graphic.
    ax1.set_title("FFT Analysis", pad=2, loc="left", fontsize=9, fontweight="bold")
    # Use a light major grid so the report remains readable without masking the spectrum.
    ax1.grid(True, which="major", linestyle="-", alpha=0.22)
    # Show minor tick marks for easier frequency reading without adding a dense minor grid.
    ax1.minorticks_on()

    # Calculate total ripple in ppm and percent when a valid engineering reference is available.
    ppm_total = ppm(total_ripple_rms, ppm_ref)
    # Percent is the same relative quantity expressed on a 100-based scale rather than a million-based scale.
    pct_total = None if ppm_total is None else ppm_total / 10000.0
    # Start the compact first-look summary with the measured DC operating point.
    fft_summary = [f"DC: {dc_value:.6g} {unit_rms_label.strip('()rms')}"]
    # Add the total time-domain ripple magnitude in physical units.
    fft_summary.append(f"Ripple RMS: {total_ripple_rms:.5g} {unit_rms_label.strip('()rms')}")
    # Report both percent and ppm because both are useful in engineering review.
    if ppm_total is not None and pct_total is not None:
        # Keep the two representations together so the reader does not have to convert them mentally.
        fft_summary.append(f"{pct_total:.6g}% | {ppm_total:.3f} ppm ({ppm_ref_label})")
    # Determine which integrated frequency band carries the largest RMS contribution.
    dominant_band = _dominant_band_summary(band_rms)
    # Include the dominant band only when band integration produced a valid result.
    if dominant_band is not None:
        # Unpack the band result in the same order used by analyze_series_for_reports.
        band_name, band_lo, band_hi, band_value, band_ppm = dominant_band
        # Begin the line with the frequency interval and physical RMS contribution.
        band_text = f"Band: {band_name} {band_lo:g}-{band_hi:g} Hz, {band_value:.4g} {unit_rms_label.strip('()rms')}"
        # Add ppm when the reference is known.
        if band_ppm is not None:
            # Preserve the ppm value because it is the normal APS stability reporting scale.
            band_text += f" | {band_ppm:.2f} ppm"
        # Add the completed dominant-band line to the report summary.
        fft_summary.append(band_text)
    # Place the summary in the upper-right corner where it normally avoids the dominant low-frequency peaks.
    ax1.text(0.985, 0.94, "\n".join(fft_summary), transform=ax1.transAxes, ha="right", va="top", fontsize=7,
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="0.78", alpha=0.92))

    # ── Subplot 2: PSD (loglog) ──────────────────────────────────────────────
    # Capture ax2 here; the next step uses this intermediate result directly.
    ax2 = fig.add_subplot(gs[1])
    # Capture mp here; the next step uses this intermediate result directly.
    mp = (f_psd >= xmin) & (f_psd <= xmax) & (f_psd > 0)
    # Carry out this step before advancing to the next part of the function.
    ax2.loglog(f_psd[mp], np.maximum(Pxx[mp], 1e-30), color="steelblue")
    # Take this branch only when the stated operating condition is true.
    if bands:
        # Carry out this step before advancing to the next part of the function.
        _annotate_bands(ax2, bands, xmin, xmax)
        # Carry out this step before advancing to the next part of the function.
        ax2.legend(loc="upper right", fontsize=7)
    # Carry out this step before advancing to the next part of the function.
    ax2.set_xlim(xmin, xmax)
    # Carry out this step before advancing to the next part of the function.
    ax2.set_xlabel("Frequency (Hz)", fontsize=8)
    # Carry out this step before advancing to the next part of the function.
    ax2.set_ylabel(unit2_per_hz_label, fontsize=8)
    # Carry out this step before advancing to the next part of the function.
    ax2.set_title("Power Spectral Density", pad=-5, loc="left", fontsize=9)
    # Carry out this step before advancing to the next part of the function.
    _style_axes_tdk(ax2)

    # Capture peak here; the next step uses this intermediate result directly.
    peak = _max_point_in_band(f_psd, Pxx, xmin, xmax)
    # Take this branch only when the stated operating condition is true.
    if peak is not None:
        # Carry out this step before advancing to the next part of the function.
        fpk, ppk, _ = peak
        # Carry out this step before advancing to the next part of the function.
        ax2.annotate(f"MAX\n{fpk:.2f} Hz\n{ppk:.3g}",
                     xy=(fpk, ppk), xytext=(fpk * 2.0, ppk * 2.0),
                     arrowprops=dict(arrowstyle="->", color="black", lw=0.8),
                     fontsize=7)

    # ── Subplot 3: Cumulative Integrated Power ───────────────────────────────
    # Capture ax3 here; the next step uses this intermediate result directly.
    ax3 = fig.add_subplot(gs[2])
    # Capture mc here; the next step uses this intermediate result directly.
    mc = (f_cum >= xmin) & (f_cum <= xmax) & (f_cum > 0)
    # Carry out this step before advancing to the next part of the function.
    ax3.loglog(f_cum[mc], np.maximum(cum_power[mc], 1e-30), color="steelblue")
    # Take this branch only when the stated operating condition is true.
    if bands:
        # Carry out this step before advancing to the next part of the function.
        _annotate_bands(ax3, bands, xmin, xmax)
        # Carry out this step before advancing to the next part of the function.
        ax3.legend(loc="upper right", fontsize=7)
    # Carry out this step before advancing to the next part of the function.
    ax3.set_xlim(xmin, xmax)
    # Carry out this step before advancing to the next part of the function.
    ax3.set_xlabel("Frequency (Hz)", fontsize=8)
    # Carry out this step before advancing to the next part of the function.
    ax3.set_ylabel(unit2_label, fontsize=8)
    # Carry out this step before advancing to the next part of the function.
    ax3.set_title("Integrated Ripple Power  ∫PSD·df", pad=-5, loc="left", fontsize=9)
    # Carry out this step before advancing to the next part of the function.
    _style_axes_tdk(ax3)

    # Carry out this step before advancing to the next part of the function.
    ax3.text(0.02, 0.95, "\n".join(text_lines),
             transform=ax3.transAxes, fontsize=7, va="top")

    # Lower load description -- matches ripple_exec ax3.text(0.22, 0.10, ...)
    # Do not judge full-load performance until the load is high enough to make that comparison meaningful.
    if load_desc:
        # Carry out this step before advancing to the next part of the function.
        ax3.text(0.22, 0.04, load_desc,
                 transform=ax3.transAxes, fontsize=7, va="bottom", color="dimgray")

    # Footer: generation timestamp + logo inset
    # Capture gen_str here; the next step uses this intermediate result directly.
    gen_str = f"Plot generated on {datetime.now().strftime('%Y-%m-%d at %H:%M:%S')}"
    # Carry out this step before advancing to the next part of the function.
    fig.text(0.01, 0.015, gen_str, fontsize=7, ha="left", va="bottom", color="dimgray")

    # Take this branch only when the stated operating condition is true.
    if logo_path and os.path.isfile(logo_path):
        # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
        try:
            # Import this dependency locally because it is only needed on this execution path.
            from PIL import Image as _PILImage
            # Resolve the local APS/Argonne branding image used by the report output.
            logo = _PILImage.open(logo_path)
            # Capture ax_logo here; the next step uses this intermediate result directly.
            ax_logo = fig.add_axes([0.70, 0.008, 0.29, 0.065])
            # Carry out this step before advancing to the next part of the function.
            ax_logo.imshow(logo)
            # Carry out this step before advancing to the next part of the function.
            ax_logo.axis("off")
        except Exception:
            # No action is required in this branch; keep the control flow explicit.
            pass

    # Carry out this step before advancing to the next part of the function.
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    # Carry out this step before advancing to the next part of the function.
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main analysis entry point
# ---------------------------------------------------------------------------

def analyze_series_for_reports(
    df: pd.DataFrame,
    time_col: str,
    value_col: str,
    outdir: str,
    ppm_ref: Optional[float],
    ppm_ref_label: str = "engineering reference",
    bands: str = DEFAULT_BAND_STR,
    sig_threshold_ppm: float = 12.0,
    label: str = "",
    quantity_unit: str = "",
    window: str = "hann",
    nperseg: int = 16384,
    overlap: float = 0.5,
    xmin: float = DEFAULT_XMIN_HZ,
    xmax: float = DEFAULT_XMAX_HZ,
    extra_text_lines: Optional[List[str]] = None,
    auto_scale_freq: bool = True,
    channel_scale: float = 1.0,
    n_peaks: int = 2,
    logo_path: Optional[str] = None,
    scope_image_path: Optional[str] = None,
    load_desc: Optional[str] = None,
    acq_timestamp: Optional[str] = None,
    composite_png: Optional[str] = None,
    file_prefix: Optional[str] = None,
    fft_y_mode: str = "magnitude",
) -> Dict[str, object]:
    """
    Full FFT/PSD analysis for one channel.  Produces three individual PNGs
    (FFT, PSD, cumulative power) and optionally a composite 8.5x11 report page
    matching ripple_exec.py's layout.

    New parameters vs original ripple_psd.py
    -----------------------------------------
    channel_scale    : Physical scale applied to raw data before FFT
                       (e.g. 500.0 A/V for a current-shunt -- V_TO_I_SCALE in
                       ripple_exec.py).  Default 1.0 (no scaling).
    n_peaks          : FFT peaks to annotate with arrowheads (default 2).
    logo_path        : Path to ANL logo PNG for footer insets.
    scope_image_path : Path to oscilloscope capture PNG for composite inset.
    load_desc        : Free-text load description shown on integrated-power plot.
    acq_timestamp    : Data acquisition timestamp string for figure footers.
    file_prefix      : If given, prepend to all output PNG filenames.
    composite_png    : If given, write a composite 8.5x11 single-page report
                       PNG to this path in addition to the three individual PNGs.
    """
    # Create the output directory now so the following writes have a valid destination.
    os.makedirs(outdir, exist_ok=True)

    # Carry out this step before advancing to the next part of the function.
    _t, x, fs, x_dc, sampling_info = load_trace_from_df(
        df, time_col, value_col, channel_scale=channel_scale,
        resample_if_irregular=False, timing_cv_limit=1.0e-4
    )
    # Reject an imported PMM file whose time base is not consistent with the
    # fixed hardware sampling expected from the CDCU post-mortem monitor.
    _timing_cv = float(sampling_info.get("dt_cv", math.nan))
    if not np.isfinite(_timing_cv) or _timing_cv > 1.0e-4:
        raise ValueError(
            f"PMM timing is not sufficiently uniform for FFT/PSD: CV(dt)={_timing_cv:.6g}. "
            "Use an unmodified hardware PMM capture rather than live polling data."
        )
    # Capture x_ac here; the next step uses this intermediate result directly.
    x_ac = x - np.mean(x)
    # Capture total_rms_time here; the next step uses this intermediate result directly.
    total_rms_time = float(np.sqrt(np.mean(x_ac ** 2)))

    # Carry out this step before advancing to the next part of the function.
    freqs, A_rms = single_sided_fft_rms(x_ac, fs, window=window)
    # Carry out this step before advancing to the next part of the function.
    f_psd, Pxx = welch_psd(x_ac, fs, nperseg=nperseg, overlap=overlap, window=window)

    # Take this branch only when the stated operating condition is true.
    if auto_scale_freq:
        # Carry out this step before advancing to the next part of the function.
        xmin_plot, xmax_plot = _auto_freq_limits_from_psd(
            f=f_psd, Pxx=Pxx, fs=fs,
            user_xmin=xmin, user_xmax=xmax,
            floor_ratio=1e-8, pad_ratio=1.15,
        )
    else:
        # Carry out this step before advancing to the next part of the function.
        xmin_plot, xmax_plot = xmin, min(xmax, 0.5 * fs)

    # Capture integrated_power here; the next step uses this intermediate result directly.
    integrated_power = float(_psd_integral(Pxx, f_psd))
    # Capture integrated_rms here; the next step uses this intermediate result directly.
    integrated_rms = float(np.sqrt(max(integrated_power, 0.0)))
    # Parseval-style consistency check: Welch-integrated RMS should agree with time-domain RMS.
    parseval_error_pct = (100.0 * (integrated_rms - total_rms_time) / total_rms_time
                          if total_rms_time > 0 else math.nan)
    parseval_status = "PASS" if (np.isfinite(parseval_error_pct) and abs(parseval_error_pct) <= 3.0) else (
        "N/A" if not np.isfinite(parseval_error_pct) else "CHECK")
    # Capture integrated_ppm here; the next step uses this intermediate result directly.
    integrated_ppm = ppm(integrated_rms, ppm_ref)

    # Capture band_specs here; the next step uses this intermediate result directly.
    band_specs = parse_bands(bands)
    # Capture band_rms here; the next step uses this intermediate result directly.
    band_rms = []
    # Walk the collection in order so every item receives the same treatment.
    for lo, hi, name in band_specs:
        # Capture r here; the next step uses this intermediate result directly.
        r = integrate_psd_rms(Pxx, f_psd, lo, hi)
        # Add this observation to the ordered history so the sequence is preserved.
        band_rms.append((name, lo, hi, r, ppm(r, ppm_ref)))

    # Significant component table for PDF overview
    # Capture sigs here; the next step uses this intermediate result directly.
    sigs = []
    # Take this branch only when the stated operating condition is true.
    if ppm_ref is not None and ppm_ref != 0:
        # Capture m here; the next step uses this intermediate result directly.
        m = freqs >= 1.0
        # Carry out this step before advancing to the next part of the function.
        f2, a2 = freqs[m], A_rms[m]
        # Walk the collection in order so every item receives the same treatment.
        for j in np.argsort(a2)[::-1][:12]:
            # Carry out this step before advancing to the next part of the function.
            f0, a0 = float(f2[j]), float(a2[j])
            # Capture p0 here; the next step uses this intermediate result directly.
            p0 = (a0 / abs(ppm_ref)) * 1e6
            # Take this branch only when the stated operating condition is true.
            if p0 >= sig_threshold_ppm:
                # Add this observation to the ordered history so the sequence is preserved.
                sigs.append((f0, a0, p0))
            # Make sure enough samples are available before running the calculation.
            if len(sigs) >= 6:
                # The required item is resolved, so leave this loop now.
                break

    # Output file paths — prefix all individual PNGs when file_prefix is given
    # Capture _stem here; the next step uses this intermediate result directly.
    _stem   = f"{file_prefix}_{value_col}" if file_prefix else value_col
    # Capture fft_png here; the next step uses this intermediate result directly.
    fft_png = os.path.join(outdir, f"{_stem}_fft.png")
    # Capture psd_png here; the next step uses this intermediate result directly.
    psd_png = os.path.join(outdir, f"{_stem}_psd.png")
    # Capture cum_png here; the next step uses this intermediate result directly.
    cum_png = os.path.join(outdir, f"{_stem}_cum_rms.png")

    # Capture unit_rms_label here; the next step uses this intermediate result directly.
    unit_rms_label     = f"({quantity_unit}rms)"
    # Capture unit2_per_hz_label here; the next step uses this intermediate result directly.
    unit2_per_hz_label = f"{quantity_unit}^2/Hz"
    # Capture unit2_label here; the next step uses this intermediate result directly.
    unit2_label        = f"({quantity_unit}^2)"

    # Individual FFT PNG
    # Carry out this step before advancing to the next part of the function.
    plot_fft_tdk(
        freqs=freqs, A_rms=A_rms, out_png=fft_png,
        xmin=xmin_plot, xmax=xmax_plot,
        title=label,
        dc_value=x_dc, total_ripple_rms=total_rms_time,
        unit_rms_label=unit_rms_label, ppm_ref=ppm_ref, ppm_ref_label=ppm_ref_label,
        bands=band_specs, band_rms=band_rms, n_peaks=n_peaks,
        logo_path=logo_path, load_desc=load_desc, acq_timestamp=acq_timestamp,
        fft_y_mode=fft_y_mode,
    )

    # Individual PSD PNG
    # Carry out this step before advancing to the next part of the function.
    plot_psd_tdk(
        f=f_psd, Pxx=Pxx, out_png=psd_png,
        xmin=xmin_plot, xmax=xmax_plot,
        title=f"{label} PSD",
        unit2_per_hz_label=unit2_per_hz_label,
        bands=band_specs, logo_path=logo_path, acq_timestamp=acq_timestamp,
    )

    # Cumulative power
    # Carry out this step before advancing to the next part of the function.
    f_c, cum_power = cumulative_integrated_power(Pxx, f_psd)
    # Carry out this step before advancing to the next part of the function.
    lines: List[str] = list(extra_text_lines or [])
    # Capture ppm_text here; the next step uses this intermediate result directly.
    ppm_text = f"{integrated_ppm:.1f} ppm" if integrated_ppm is not None else "ppm: N/A"
    # Add this observation to the ordered history so the sequence is preserved.
    lines.append(f"Integrated RMS = {integrated_rms:.4g}{quantity_unit} ({ppm_text}; ref={ppm_ref_label})")
    # Walk the collection in order so every item receives the same treatment.
    for name, _lo, _hi, r_rms, r_ppm in band_rms:
        # Capture ppm_str here; the next step uses this intermediate result directly.
        ppm_str = f"{r_ppm:.1f} ppm" if r_ppm is not None else "N/A ppm"
        # Add this observation to the ordered history so the sequence is preserved.
        lines.append(f"  [{name}] RMS={r_rms:.4g}{quantity_unit} ({ppm_str})")

    # Individual cumulative power PNG
    # Carry out this step before advancing to the next part of the function.
    plot_integrated_power_tdk(
        f=f_c, cum_power=cum_power, out_png=cum_png,
        xmin=xmin_plot, xmax=xmax_plot,
        title="Integrated Ripple Power   integral(PSD)df",
        unit2_label=unit2_label, text_lines=lines,
        bands=band_specs, load_desc=load_desc,
        logo_path=logo_path, acq_timestamp=acq_timestamp,
    )

    # Optional composite 8.5x11 report PNG
    # Carry out this step before advancing to the next part of the function.
    comp_png_path: Optional[str] = None
    # Take this branch only when the stated operating condition is true.
    if composite_png:
        # Resolve comp_png_path once so later file operations use the same location.
        comp_png_path = composite_png
        # Carry out this step before advancing to the next part of the function.
        plot_composite_report(
            freqs=freqs, A_rms=A_rms,
            f_psd=f_psd, Pxx=Pxx,
            f_cum=f_c, cum_power=cum_power,
            out_png=comp_png_path,
            xmin=xmin_plot, xmax=xmax_plot,
            title=label,
            dc_value=x_dc, total_ripple_rms=total_rms_time,
            unit_rms_label=unit_rms_label,
            unit2_per_hz_label=unit2_per_hz_label,
            unit2_label=unit2_label,
            ppm_ref=ppm_ref, ppm_ref_label=ppm_ref_label, text_lines=lines,
            bands=band_specs, band_rms=band_rms, n_peaks=n_peaks,
            logo_path=logo_path, scope_image_path=scope_image_path,
            load_desc=load_desc, acq_timestamp=acq_timestamp,
            fft_y_mode=fft_y_mode,
        )

    # Summary text file
    # Capture summary_txt here; the next step uses this intermediate result directly.
    summary_txt = os.path.join(outdir, "summary.txt")
    # Use a context manager so the file or resource is closed cleanly on every exit path.
    with open(summary_txt, "w", encoding="utf-8") as fh:
        # Write this field to the report in the same order an engineer will review it.
        fh.write(f"{label}\n")
        # Write this field to the report in the same order an engineer will review it.
        fh.write(f"value_col={value_col}\n")
        # Write this field to the report in the same order an engineer will review it.
        fh.write(f"channel_scale={channel_scale}\n")
        # Write this field to the report in the same order an engineer will review it.
        fh.write(f"fs_hz={fs:.6f}\n")
        # Write this field to the report in the same order an engineer will review it.
        fh.write(f"dc_value={x_dc:.9g} {quantity_unit}\n")
        fh.write(f"ppm_ref={ppm_ref}\n")
        fh.write(f"ppm_ref_label={ppm_ref_label}\n")
        # Write this field to the report in the same order an engineer will review it.
        fh.write(f"total_rms_time={total_rms_time:.9g} {quantity_unit}\n")
        # Write this field to the report in the same order an engineer will review it.
        fh.write(f"integrated_psd_power={integrated_power:.9g} {quantity_unit}^2\n")
        # Write this field to the report in the same order an engineer will review it.
        fh.write(f"integrated_rms={integrated_rms:.9g} {quantity_unit}\n")
        fh.write(f"parseval_error_pct={parseval_error_pct:.6g}\n")
        fh.write(f"parseval_status={parseval_status}\n")
        fh.write(f"timing_dt_cv={sampling_info.get('dt_cv')}\n")
        fh.write(f"timing_resampled={sampling_info.get('resampled')}\n")
        # Take this branch only when the stated operating condition is true.
        if integrated_ppm is not None:
            # Write this field to the report in the same order an engineer will review it.
            fh.write(f"integrated_rms_ppm={integrated_ppm:.3f}\n")
        # Write this field to the report in the same order an engineer will review it.
        fh.write(f"\nfft_y_mode={fft_y_mode}\n")
        fh.write(f"plot_xmin_hz={xmin_plot:.6g}\n")
        # Write this field to the report in the same order an engineer will review it.
        fh.write(f"plot_xmax_hz={xmax_plot:.6g}\n")
        # Write this field to the report in the same order an engineer will review it.
        fh.write("\nBand RMS:\n")
        # Walk the collection in order so every item receives the same treatment.
        for name, _lo, _hi, r_rms, r_ppm in band_rms:
            # Capture ppm_str here; the next step uses this intermediate result directly.
            ppm_str = f"{r_ppm:.3f}" if r_ppm is not None else "N/A"
            # Write this field to the report in the same order an engineer will review it.
            fh.write(f"  {name}: rms={r_rms:.9g} {quantity_unit}, ppm={ppm_str}\n")

    # Hand the finished value back to the caller.
    return {
        "label":              label,
        "value_col":          value_col,
        "outdir":             outdir,
        "fs_hz":              fs,
        "fft_png":            fft_png,
        "psd_png":            psd_png,
        "cum_png":            cum_png,
        "composite_png":      comp_png_path,
        "summary_txt":        summary_txt,
        "dc_value":           x_dc,
        "total_rms_time":     total_rms_time,
        "integrated_power":   integrated_power,
        "integrated_rms":     integrated_rms,
        "integrated_rms_ppm": integrated_ppm,
        "parseval_error_pct": parseval_error_pct,
        "parseval_status":    parseval_status,
        "sampling_info":      sampling_info,
        "band_rms":           band_rms,
        "sig_components":     sigs,
        "sig_threshold_ppm":  sig_threshold_ppm,
        "ppm_ref":            ppm_ref,
        "ppm_ref_label":      ppm_ref_label,
        "quantity_unit":      quantity_unit,
        "xmin_hz":            xmin_plot,
        "xmax_hz":            xmax_plot,
        "fft_y_mode":          fft_y_mode,
    }
