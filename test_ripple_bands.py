#!/usr/bin/env python3
"""Regression checks for the standard CDCU PMM spectral bands."""

import math
import numpy as np

from cdcu_ripple_bands import ANALYSIS_BANDS, BAND_STR
from cdcu_ripple_psd import parse_bands, welch_psd, integrate_psd_rms


def main() -> None:
    parsed = parse_bands(BAND_STR)
    assert parsed == ANALYSIS_BANDS

    one_khz_band = [b for b in ANALYSIS_BANDS if b[0] < 1000.0 < b[1]]
    assert len(one_khz_band) == 1, ANALYSIS_BANDS
    lo, hi, label = one_khz_band[0]
    assert (lo, hi, label) == (720.0, 1200.0, "720-1200 Hz")

    # 1.000 A RMS sinusoid at 1 kHz, sampled exactly like the CDCU PMM.
    fs = 10_000.0
    n = 100_001
    t = np.arange(n, dtype=float) / fs
    x = math.sqrt(2.0) * np.sin(2.0 * np.pi * 1000.0 * t)

    f, pxx = welch_psd(x, fs=fs, nperseg=16384)
    rms_1k_band = integrate_psd_rms(pxx, f, lo, hi)
    rms_lower_band = integrate_psd_rms(pxx, f, 360.0, 720.0)

    assert 0.98 <= rms_1k_band <= 1.02, rms_1k_band
    assert rms_lower_band < 0.01, rms_lower_band

    print("ripple band tests: PASS")
    print(f"1 kHz integrated RMS in {label}: {rms_1k_band:.6f} A")


if __name__ == "__main__":
    main()
